#!/usr/bin/env python

import numpy as np
import astropy.units as units
import racs_tools.gaussft as gaussft


def convolve(image, old_beam, new_beam, u, v):
    """Convolve by X-ing in the Fourier domain.

    Args:
        image (2D array): The image to be convolved.
        old_beam (radio_beam.Beam): Current image PSF.
        new_beam (radio_beam.Beam): Target image PSF.
        u (float): Fourier coordinate corresponding to x 
        v (float): Fourier coordinate corresponding to y 

    Returns:
        tuple: (conolved image, scaling factor)
    """
    nx = image.shape[0]
    ny = image.shape[1]

    g_final = np.zeros((nx,ny),dtype=float)
    [g_final,g_ratio] = gaussft.gaussft(bmin_in=old_beam.minor.to(units.deg).value, 
                                    bmaj_in=old_beam.major.to(units.deg).value, 
                                    bpa_in=old_beam.pa.to(units.deg).value,
                                    bmin=new_beam.minor.to(units.deg).value,
                                    bmaj=new_beam.major.to(units.deg).value,
                                    bpa=new_beam.pa.to(units.deg).value,
                                    u=u, v=v,
                                    nx=nx, ny=ny)
    # Perform the x-ing in the FT domain
    im_f = np.fft.fft2(image)

    # Now convolve with the desired Gaussian:
    M = np.multiply(im_f,g_final)
    im_conv = np.fft.ifft2(M)
    im_conv = np.real(im_conv)

    # print("factor: %f" % g_ratio)
    # print("dx: %s" % dx)
    # print("dy: %s" % dy)
    # tmp = old_beam.minor.to(units.deg).value
    # print("bMaj psf: %f , %f" % (tmp,tmp*3600))
    # tmp = bmin_in
    # print("bMaj psf: %f , %f" % (tmp,tmp*3600.0))
    # tmp = bpa_in
    # print("bPA psf: %f " % tmp)
    # tmp = bmaj
    # print("bMaj desired: %f, %f" % (tmp,tmp*3600.0))
    # tmp = bmin
    # print("bMin desired: %f, %f" % (tmp,tmp*3600.0))
    # tmp = bpa
    # print("bPA desired: %f " % tmp)
    return im_conv, g_ratio
