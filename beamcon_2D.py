#!/usr/bin/env python
import os
import sys
import numpy as np
import scipy.signal
from astropy import units as u
from astropy.io import fits
from radio_beam import Beam, Beams
from radio_beam.utils import BeamError
from glob import glob
import au2
import functools
import schwimmbad
import psutil
print = functools.partial(print, f'[{psutil.Process().cpu_num()}]', flush=True)

#############################################
#### ADAPTED FROM SCRIPT BY T. VERNSTROM ####
#############################################


def round_up(n, decimals=0):
    multiplier = 10 ** decimals
    return np.ceil(n * multiplier) / multiplier


def getbeam(datadict, new_beam, verbose=False):
    """Get beam info
    """
    if verbose:
        print(f"Current beam is", datadict['oldbeam'])

    conbm = new_beam.deconvolve(datadict['oldbeam'])
    fac, amp, outbmaj, outbmin, outbpa = au2.gauss_factor(
        [
            conbm.major.to(u.arcsec).value,
            conbm.minor.to(u.arcsec).value,
            conbm.pa.to(u.deg).value
        ],
        beamOrig=[
            datadict['oldbeam'].major.to(u.arcsec).value,
            datadict['oldbeam'].minor.to(u.arcsec).value,
            datadict['oldbeam'].pa.to(u.deg).value
        ],
        dx1=datadict['dx'].to(u.arcsec).value,
        dy1=datadict['dy'].to(u.arcsec).value
    )

    return conbm, fac


def getimdata(cubenm, verbose=False):
    """Get fits image data
    """
    if verbose:
        print(f'Getting image data from {cubenm}')
    with fits.open(cubenm, memmap=True, mode='denywrite') as hdu:

        dxas = hdu[0].header['CDELT1']*-1*u.deg
        dyas = hdu[0].header['CDELT2']*u.deg

        nx, ny = hdu[0].data[0, 0, :,
                             :].shape[0], hdu[0].data[0, 0, :, :].shape[1]

        old_beam = Beam.from_fits_header(
            hdu[0].header
        )

        datadict = {
            'image': hdu[0].data[0, 0, :, :],
            'header': hdu[0].header,
            'oldbeam': old_beam,
            'nx': nx,
            'ny': ny,
            'dx': dxas,
            'dy': dxas
        }
    return datadict


def smooth(datadict, verbose=False):
    """Do the smoothing
    """
    # using Beams package
    if verbose:
        print(f'Smoothing so beam is', datadict["final_beam"])
        print(f'Using convolving beam', datadict["conbeam"])
    pix_scale = datadict['dy']

    gauss_kern = datadict["conbeam"].as_kernel(pix_scale)

    conbm1 = gauss_kern.array/gauss_kern.array.max()

    newim = scipy.signal.convolve(
        datadict['image'].astype('f8'), conbm1, mode='same')

    newim *= datadict["sfactor"]
    return newim


def savefile(datadict, filename, outdir='.', verbose=False):
    """Save file to disk
    """
    outfile = f'{outdir}/{filename}'
    if verbose:
        print(f'Saving to {outfile}')
    header = datadict['header']
    beam = datadict['final_beam']
    header = beam.attach_to_header(header)
    fits.writeto(outfile, datadict['newimage'], header=header, overwrite=True)


def worker(args):
    file, outdir, new_beam, clargs, verbose = args
    if verbose:
        print(f'Working on {file}')

    outfile = os.path.basename(file)
    outfile = outfile.replace('.fits', '.sm.fits')
    if clargs.prefix is not None:
        outfile = clargs.prefix + outfile
    datadict = getimdata(file)

    conbeam, sfactor = getbeam(
        datadict,
        new_beam,
        verbose=verbose
    )

    datadict.update(
        {
            "conbeam": conbeam,
            "final_beam": new_beam,
            "sfactor": sfactor
        }
    )

    newim = smooth(datadict, verbose=verbose)

    datadict.update(
        {
            "newimage": newim,
        }
    )

    savefile(datadict, outfile, outdir, verbose=verbose)


def getmaxbeam(files, tolerance=0.0001, nsamps=200, epsilon=0.0005, verbose=False):
    """Get largest beam
    """
    beams = []
    for file in files:
        header = fits.getheader(file, memmap=True)
        beam = Beam.from_fits_header(header)
        beams.append(beam)

    beams = Beams(
        [beam.major.value for beam in beams]*u.deg,
        [beam.minor.value for beam in beams]*u.deg,
        [beam.pa.value for beam in beams]*u.deg
    )
    try:
        cmn_beam = beams.common_beam(
            tolerance=tolerance, epsilon=epsilon, nsamps=nsamps)
    except BeamError:
        if verbose:
            print("Couldn't find common beam with defaults")
            print("Trying again with smaller tolerance")
        cmn_beam = beams.common_beam(
            tolerance=tolerance*0.1, epsilon=epsilon, nsamps=nsamps)
    return cmn_beam


def main(pool, args, verbose=False):
    """Main script
    """
    if args.dryrun:
        if verbose:
            print('Doing a dry run -- no files will be saved')
    # Fix up outdir
    outdir = args.outdir
    if outdir is not None:
        if outdir[-1] == '/':
            outdir = outdir[:-1]
    else:
        outdir = '.'

    # Get file list
    files = glob(args.infile)
    if files == []:
        raise Exception('No files found!')

    # Parse args
    bmaj = args.bmaj
    bmin = args.bmin
    bpa = args.bpa

    # Find largest bmax
    big_beam = getmaxbeam(files,
                          tolerance=args.tolerance,
                          nsamps=args.nsamps, 
                          epsilon=args.epsilon, 
                          verbose=verbose)

    # Set to largest
    if bpa is None and bmin is None and bmaj is None:
        bpa = big_beam.pa.to(u.deg)
    else:
        bpa = 0*u.deg
    if bmaj is None:
        bmaj = round_up(big_beam.major.to(u.arcsec))
    elif bmaj*u.arcsec < round_up(big_beam.major.to(u.arcsec)):
        raise Exception('Selected BMAJ is too small!')
    else:
        bmaj *= u.arcsec
    if bmin is None:
        bmin = round_up(big_beam.minor.to(u.arcsec))
    elif bmin*u.arcsec < round_up(big_beam.minor.to(u.arcsec)):
        raise Exception('Selected BMIN is too small!')
    else:
        bmin *= u.arcsec

    new_beam = Beam(
        bmaj,
        bmin,
        bpa
    )
    if verbose:
        print(f'Final beam is', new_beam)

    inputs = [[file, outdir, new_beam, args, verbose]
              for i, file in enumerate(files)]

    if not args.dryrun:
        output = list(pool.map(worker, inputs))

    if verbose:
        print('Done!')


def cli():
    """Command-line interface
    """
    import argparse

    # Help string to be shown using the -h option
    descStr = """
    Smooth a field of 2D images to a common resolution.

    Names of output files are 'infile'.sm.fits

    NOTE: Glob is used to parse wildcards. So if you want to run on 
        *.fits, use: python beamcon_2D.py '*.fits'
        i.e. parse the wildcard as a string.

    """

    # Parse the command line options
    parser = argparse.ArgumentParser(description=descStr,
                                     formatter_class=argparse.RawTextHelpFormatter)

    parser.add_argument(
        'infile',
        metavar='infile',
        type=str,
        help='Input FITS image(s) to smooth (can be a wildcard) - beam info must be in header.')

    parser.add_argument(
        '-p',
        '--prefix',
        dest='prefix',
        type=str,
        default=None,
        help='Add prefix to output filenames.')

    parser.add_argument(
        '-o',
        '--outdir',
        dest='outdir',
        type=str,
        default=None,
        help='Output directory of smoothed FITS image(s) [./].')

    parser.add_argument("-v", "--verbose", dest="verbose", action="store_true",
                        help="verbose output [False].")

    parser.add_argument("-d", "--dryrun", dest="dryrun", action="store_true",
                        help="Compute common beam and stop [False].")

    parser.add_argument(
        "--bmaj",
        dest="bmaj",
        type=float,
        default=None,
        help="BMAJ to convolve to [max BMAJ from given image(s)].")

    parser.add_argument(
        "--bmin",
        dest="bmin",
        type=float,
        default=None,
        help="BMIN to convolve to [max BMAJ from given image(s)].")

    parser.add_argument(
        "--bpa",
        dest="bpa",
        type=float,
        default=None,
        help="BPA to convolve to [0].")

    parser.add_argument(
        "-t",
        "--tolerance",
        dest="tolerance",
        type=float,
        default=0.0001,
        help="tolerance for radio_beam.commonbeam.")

    parser.add_argument(
        "-e",
        "--epsilon",
        dest="epsilon",
        type=float,
        default=0.0005,
        help="epsilon for radio_beam.commonbeam.")

    parser.add_argument(
        "-n",
        "--nsamps",
        dest="nsamps",
        type=int,
        default=200,
        help="nsamps for radio_beam.commonbeam.")

    group = parser.add_mutually_exclusive_group()

    group.add_argument("--ncores", dest="n_cores", default=1,
                       type=int, help="Number of processes (uses multiprocessing).")
    group.add_argument("--mpi", dest="mpi", default=False,
                       action="store_true", help="Run with MPI.")

    args = parser.parse_args()

    pool = schwimmbad.choose_pool(mpi=args.mpi, processes=args.n_cores)
    if args.mpi:
        if not pool.is_master():
            pool.wait()
            sys.exit(0)

    verbose = args.verbose

    main(pool, args, verbose=verbose)
    pool.close()


if __name__ == "__main__":
    cli()
