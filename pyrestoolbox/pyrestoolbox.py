"""
    pyResToolbox - A collection of Reservoir Engineering Utilities
              Copyright (C) 2022, Mark Burgoyne

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    The GNU General Public License can be found in the LICENSE directory, 
    and at  <https://www.gnu.org/licenses/>.

          Contact author at mark.w.burgoyne@gmail.com
"""

import numpy as np
import numpy.typing as npt
from scipy.integrate import quad
import pandas as pd
from collections import Counter
import glob
from tabulate import tabulate
import sys
import numdifftools as nd
from enum import Enum

class z_method(Enum): # Gas Z-Factor calculation model
    DAK = 0
    LIN = 1
    HY = 2
    
class c_method(Enum): # Gas critical properties calculation method
    PMC = 0
    SUT = 1

class pb_method(Enum): # Bubble point calculation method
    STAN = 0
    VALMC = 1
    VELAR = 2

class rs_method(Enum): # Oil solution gas calculation method
    VELAR = 0
    STAN = 1
    VASBG = 2
                    
class bo_method(Enum): # Oil FVF calculation method
    VELAR = 0
    STAN = 1
 
class uo_method(Enum): # Oil viscosity calculation method
    BR = 0

class deno_method(Enum): # Oil Density calculation method
    SWMH = 0
    #STAN = 1
    
class co_method(Enum): # Oil compressibility calculation method
    SPIV = 0
    #VASBG = 1
    
class kr_family(Enum): # Relative permeability family type
    COR = 0
    LET = 1

class kr_table(Enum): # Relative permeability table type
    SWOF = 0
    SGOF = 1
    SGWFN = 2


def bisect_solve(args, f, xmin, xmax, rtol):
    err_hi = f(args, xmax)
    err_lo = f(args, xmin)
    iternum = 0
    err_mid = 1
    while abs(err_mid) > rtol:
        mid_val = (xmax + xmin) / 2
        err_mid = f(args, mid_val)        
        iternum += 1
        if iternum > 99:
            print('Could not solve via bisection')
            sys.exit()
        if err_hi * err_mid < 0:        # Solution point must be higher than current mid_val case
            xmin = mid_val
            err_lo = err_mid
            mid_val = (mid_val + xmax) / 2
        else:
            xmax = mid_val              # Other_wise must be lower than current mid_val case
            err_hi = err_mid
    return mid_val
    
def gas_rate_radial(k: npt.ArrayLike, h: npt.ArrayLike, pr: npt.ArrayLike, pwf: npt.ArrayLike, r_w: float, r_ext: float, degf: float, zmethod: z_method=z_method.DAK, cmethod: c_method=c_method.PMC, S: float = 0, D: float = 0, sg: float = 0.75, n2: float = 0, co2: float = 0, h2s: float = 0, tc: float = 0, pc: float = 0)-> np.ndarray:
    """ Returns gas rate for radial flow (mscf/day) using Darcy pseudo steady state equation & gas pseudopressure
        k: Permeability (mD)
        h: Net flow height (ft)
        pr: Reservoir pressure (psia)
        pwf: BHFP (psia)
        r_w: Wellbore Radius (ft)
        r_ext: External Reservoir Radius (ft)
        zmethod: Method for calculating Z-Factor
                 'LIN' A linearized form (a bit faster) using https://link.springer.com/article/10.1007/s13202-015-0209-3,
                 'DAK' Dranchuk & Abou-Kassem (1975) using from Equations 2.7-2.8 from 'Petroleum Reservoir Fluid Property Correlations' by W. McCain et al.
                 'HY' Hall & Yarborough (1973)
                 defaults to 'DAK' if not specified
        cmethod: Method for calculting critical properties
               'SUT' for Sutton with Wichert & Aziz non-hydrocarbon corrections, or 
               'PMC' for Piper, McCain & Corredor (1999) correlation, using equations 2.4 - 2.6 from 'Petroleum Reservoir Fluid Property Correlations' by W. McCain et al.
               Defaults to 'PMC'
        tc: Critical gas temperature (deg R). Uses cmethod correlation if not specified
        pc: Critical gas pressure (psia). Uses cmethod correlation if not specified
        n2: Molar fraction of Nitrogen. Defaults to zero if undefined 
        co2: Molar fraction of CO2. Defaults to zero if undefined  
        h2s: Molar fraction of H2S. Defaults to zero if undefined   
        S: Skin. Defaults to zero if undefined
        D: Non Darcy Skin Factor (day/mscf). Defaults to zero if undefined
        sg: Gas SG relative to air, Defaults to 0.75 if undefined
        degf: Reservoir Temperature (deg F). Defaults to False if undefined
    """
    k, h, pr, pwf = np.asarray(k), np.asarray(h), np.asarray(pr), np.asarray(pwf)
    if type(zmethod)==str:
        try:
            zmethod = z_method[zmethod.upper()]
        except:
            print('Incorrect zmethod specified')
            sys.exit()
    if type(cmethod)==str:
        try:
            cmethod = c_method[cmethod.upper()]
        except:
            print('Incorrect cmethod specified')
            sys.exit()
        
    tc, pc = gas_tc_pc(sg, n2, co2, h2s, cmethod.name, tc, pc)
    
    direction = 1
    if pr < pwf:
        direction = -1 # Direction is needed because solving the quadratic with non-Darcy factor will fail if using a negative delta_mp
        pwf, pr = pr, pwf

    delta_mp = deltamp(p1=pwf, p2=pr, degf=degf, sg=sg, zmethod=zmethod, cmethod=cmethod, tc=tc, pc=pc, n2=n2, co2=co2, h2s=h2s)
    qg = darcy_gas(delta_mp, k, h, degf, r_w, r_ext, S, D, radial=True)
    return direction*qg

def gas_rate_linear(k: npt.ArrayLike, h: npt.ArrayLike, pr: npt.ArrayLike, pwf: npt.ArrayLike, width: float, length: float, degf: float, zmethod: z_method=z_method.DAK, cmethod: c_method=c_method.PMC, S: float = 0, D: float = 0, sg: float = 0.75, n2: float = 0, co2: float = 0, h2s: float = 0, tc: float = 0, pc: float = 0)-> np.ndarray:
    """ Returns gas rate for linear flow (mscf/day) using Darcy steady state equation & gas pseudopressure
        k: Permeability (mD)
        h: Net height of low area (ft)
        pr: Reservoir pressure (psia)
        pwf: BHFP (psia)
        width: Width of flow area (ft)
        length: Linear distance of flow (ft)
        zmethod: Method for calculating Z-Factor
                 'LIN' A linearized form (a bit faster) using https://link.springer.com/article/10.1007/s13202-015-0209-3,
                 'DAK' Dranchuk & Abou-Kassem (1975) using from Equations 2.7-2.8 from 'Petroleum Reservoir Fluid Property Correlations' by W. McCain et al.
                 'HY' Hall & Yarborough (1973)
                 defaults to 'DAK' if not specified
        cmethod: Method for calculting critical properties
               'SUT' for Sutton with Wichert & Aziz non-hydrocarbon corrections, or 
               'PMC' for Piper, McCain & Corredor (1999) correlation, using equations 2.4 - 2.6 from 'Petroleum Reservoir Fluid Property Correlations' by W. McCain et al.
               Defaults to 'PMC' if not specified
        tc: Critical gas temperature (deg R). Uses cmethod correlation if not specified
        pc: Critical gas pressure (psia). Uses cmethod correlation if not specified
        n2: Molar fraction of Nitrogen. Defaults to zero if not specified 
        co2: Molar fraction of CO2. Defaults to zero if not specified  
        h2s: Molar fraction of H2S. Defaults to zero if not specified   
        S: Skin. Defaults to zero if not specified
        D: Non Darcy Skin Factor (day/mscf). Defaults to zero if not specified
        sg: Gas SG relative to air, Defaults to 0.75 if not specified
        degf: Reservoir Temperature (deg F). 
    """
    k, h, pr, pwf = np.asarray(k), np.asarray(h), np.asarray(pr), np.asarray(pwf)
    if type(zmethod)==str:
        try:
            zmethod = z_method[zmethod.upper()]
        except:
            print('Incorrect zmethod specified')
            sys.exit()
    if type(cmethod)==str:
        try:
            cmethod = c_method[cmethod.upper()]
        except:
            print('Incorrect cmethod specified')
            sys.exit()
        
    tc, pc = gas_tc_pc(sg, n2, co2, h2s, cmethod.name, tc, pc)
    
    direction = 1
    if pr < pwf:
        direction = -1 # Direction is needed because solving the quadratic with non-Darcy factor will fail if using a negative delta_mp
        pwf, pr = pr, pwf

    delta_mp = deltamp(p1=pwf, p2=pr, degf=degf, sg=sg, zmethod=zmethod, cmethod=cmethod, tc=tc, pc=pc, n2=n2, co2=co2, h2s=h2s)
    qg = darcy_gas(delta_mp, k, h, degf, width, length, S, D, radial=False)
    return direction*qg

def darcy_gas(delta_mp: npt.ArrayLike, k: npt.ArrayLike, h: npt.ArrayLike, degf: float, l1: float, l2: float, S: float, D: float, radial: bool)-> np.ndarray:
    # Returns mscf/day gas rate. k (mD), h (ft), t (deg F), l1 (r_w or width)/l2 (re or length) (ft), S(Skin), D(Day/mscf)
    tr = degf + 460
    if radial:
        a = k * h * delta_mp
        b = 1422 * tr
        c = np.log(l2 / l1) - 0.75 + S
        if D > 1e-9: # Solve analytically for rate with non-Darcy factor by rearranging into root of a quadratic equation.
            return (np.sqrt(4 * a * b * D + (b * b * c * c)) - (b * c)) / (2 * b * D)
    else:
        a = k * h* l1 * delta_mp
        b = 2*np.pi*1422*tr
        c = l2       
    # Else, ignore non-Darcy skin
    return a / (b * c)

def gas_tc_pc(sg: float, n2:float=0, co2:float=0, h2s:float=0, cmethod:str='PMC', tc:float=0, pc:float=0) -> tuple:
    """ Returns a tuple of critical temperature (deg R) and critical pressure (psia) for hydrocarbon gas 
        cmethod: 'SUT' for Sutton with Wichert & Aziz non-hydrocarbon corrections, or 
                 'PMC' for Piper, McCain & Corredor (1999) correlation, using equations 2.4 - 2.6 from 'Petroleum Reservoir Fluid Property Correlations' by W. McCain et al.
        sg: Specific gravity of reservoir gas (relative to air)
        n2: Molar fraction of Nitrogen. Defaults to zero if undefined 
        co2: Molar fraction of CO2. Defaults to zero if undefined  
        h2s: Molar fraction of H2S. Defaults to zero if undefined  
        tc: Critical gas temperature (deg R). Uses cmethod correlation if not specified
        pc: Critical gas pressure (psia). Uses cmethod correlation if not specified 
    """
    if tc*pc > 0: # Critical properties have been user specified
        return (tc,pc)

    if cmethod == 'PMC': # Piper, McCain & Corredor (1999) 
        y = np.array([0, h2s, co2, n2])
        alpha = np.array([0.11582, -0.4582, -0.90348, -0.66026, 0.70729, -0.099397])
        beta = np.array([3.8216, -0.06534, -0.42113, -0.91249, 17.438, -3.2191])
        tci = np.array([0, 672.35, 547.58, 239.26])
        pci = np.array([0, 1306.0, 1071.0, 507.5])
        j = alpha[0] + (alpha[4] * sg) + (alpha[5] * sg * sg) #2.5
        k = beta[0] + (beta[4] * sg) + (beta[5] * sg * sg) #2.6
        jt = j
        kt = k
        jt += sum([(alpha[i] * y[i] * tci[i] / pci[i]) for i in range(1,4)])
        kt += sum((beta[i] * y[i] * tci[i] / np.sqrt(pci[i])) for i in range(1,4))
        tpc = kt * kt / jt #2.4
        j += sum([alpha[i]*y[i]*tci[i]/pci[i] for i in range(1,4)])
        k += sum([beta[i] * y[i] * tci[i] / np.sqrt(pci[i]) for i in range(1,4)])
        ppc = (k * k / j) / j
        #return (tpc, ppc)
    elif cmethod == 'SUT': # Sutton equations with Wichert & Aziz non-hydrocarbon corrections from monograph
        sg_hc = (sg - (n2*28.01 + co2*44.01 + h2s*34.1)/28.966)/(1-n2-co2-h2s) # Eq 3.53
        eps = 120*((co2+h2s)**0.9 - (co2+h2s)**1.6)+15*(h2s**0.5-h2s**4) # Eq 3.52c
        ppc_hc = 756.8 - 131.0*sg_hc - 3.6*sg_hc**2 # Eq 3.47b
        tpc_hc = 169.2 + 349.5*sg_hc - 74.0*sg_hc**2 # Eq 3.47a
        ppc_star = (1-n2-co2-h2s)*ppc_hc + n2*507.5 + co2*1071.0 + h2s*1306.0 # Eq 3.54a
        tpc_star = (1-n2-co2-h2s)*tpc_hc + n2*239.26 + co2*547.58 + h2s*672.35 # Eq 3.54b
        tpc = tpc_star - eps # Eq 3.52a
        ppc = ppc_star*(tpc_star-eps)/(tpc_star + h2s*(1-h2s)*eps) # Eq. 3,52b

    else:
        print('Incorrect cmethod specified')
        sys.exit()
    
    if tc > 0:
        tpc = tc
    if pc > 0:
        ppc = pc
    return (tpc, ppc) 
                
def gas_z(p: npt.ArrayLike, sg: float, degf: float, zmethod: z_method=z_method.DAK, cmethod: c_method=c_method.PMC, n2: float = 0, co2: float = 0, h2s: float = 0, tc: float = 0, pc: float = 0)-> np.ndarray:
    """ Returns real-gas deviation factor (Z)     
        p: Gas pressure (psia)
        sg: Gas SG relative to air. Defaults to False if undefined
        pwf: BHFP (psia)
        degf: Gas Temperature (deg F)
        zmethod: Method for calculating Z-Factor
                 'LIN' A linearized form (a bit faster) using https://link.springer.com/article/10.1007/s13202-015-0209-3,
                 'DAK' Dranchuk & Abou-Kassem (1975) using from Equations 2.7-2.8 from 'Petroleum Reservoir Fluid Property Correlations' by W. McCain et al.
                 'HY' Hall & Yarborough (1973)
                 defaults to 'DAK' if not specified
        cmethod: Method for calculting critical properties
               'SUT' for Sutton with Wichert & Aziz non-hydrocarbon corrections, or 
               'PMC' for Piper, McCain & Corredor (1999) correlation, using equations 2.4 - 2.6 from 'Petroleum Reservoir Fluid Property Correlations' by W. McCain et al.
               Defaults to 'PMC'
        tc: Critical gas temperature (deg R). Uses cmethod correlation if not specified
        pc: Critical gas pressure (psia). Uses cmethod correlation if not specified
        n2: Molar fraction of Nitrogen. Defaults to zero if undefined 
        co2: Molar fraction of CO2. Defaults to zero if undefined  
        h2s: Molar fraction of H2S. Defaults to zero if undefined   
    """
    p = np.asarray(p)
    if type(zmethod)==str:
        try:
            zmethod = z_method[zmethod.upper()]
        except:
            print('Incorrect zmethod specified')
            sys.exit()
    if type(cmethod)==str:
        try:
            cmethod = c_method[cmethod.upper()]
        except:
            print('Incorrect cmethod specified')
            sys.exit()
        
    tc, pc = gas_tc_pc(sg, n2, co2, h2s, cmethod.name, tc, pc)
       
    # Explicit calculation of Z-Factor, 
    # Approx half the time needed vs DAK approach below
    def z_lin(p, degf, sg, tc, pc):
        # https://link.springer.com/article/10.1007/s13202-015-0209-3
        if type(p) == list:
            p=np.array(p)
        pr = p / pc
        tr = (degf + 460) / tc
        a = np.array([0, 0.317842,0.382216,-7.768354,14.290531,0.000002,-0.004693,0.096254,0.16672,0.96691,0.063069,-1.966847,21.0581,-27.0246,16.23,207.783,-488.161,176.29,1.88453,3.05921])
        t = 1/tr
        A = a[1]*t*np.exp(a[2]*(1-t)**2)*pr
        B = a[3]*t+a[4]*t**2+a[5]*t**6*pr**6
        C = a[9]+a[8]*t*pr+a[7]*t**2*pr**2+a[6]*t**3*pr**3
        D = a[10]*t*np.exp(a[11]*(1-t)**2)
        E = a[12]*t+a[13]*t**2+a[14]*t**3
        F = a[15]*t+a[16]*t**2+a[17]*t**3
        G = a[18]+a[19]*t
        y = D*pr/((1+A**2)/C - (A**2*B/C**3))
        return  D*pr*(1+y+y**2-y**3)/(D*pr+E*y**2-F*y**G)/(1-y)**3

    def zdak(p, degf, sg, tc, pc):
        # DAK from Equations 2.7-2.8 from 'Petroleum Reservoir Fluid Property Correlations' by W. McCain et al.
        # sg relative to air, t in deg F, p in psia, n2, co2 and h2s in % (0-100)
        
        def Eq2p7(pr, tr, rhor, a):
            z_calc = 1 + (a[1] + (a[2] / tr) + (a[3] / (tr * tr * tr)) + (a[4] / (tr * tr * tr * tr)) + (a[5] / np.power(tr, 5))) * rhor + ((a[6] + (a[7] / tr) + (a[8] / (tr * tr))) * rhor * rhor) - (a[9] * ((a[7] / tr) + (a[8] / (tr * tr))) * np.power(rhor, 5)) + (a[10] * (1 + (a[11] * rhor * rhor)) * (rhor * rhor / np.power(tr, 3)) * np.exp(-a[11] * rhor * rhor))
            return z_calc
        
        zout = []
        single_p = False
        if p.size == 1:
            single_p = True
            ps = [p]
        else:
            ps = p.tolist()
            
        for p in ps: 
            pr = p / pc
            tr = (degf + 460) / tc
            a = np.array([0, 0.3265, -1.07, -0.5339, 0.01569, -0.05165, 0.5475, -0.7361, 0.1844, 0.1056, 0.6134, 0.7210])

            # Start with Z = 1.0
            z = 1.0 
            rhor = 0.27 * pr / (tr * z) # 2.8
            
            z2 = Eq2p7(pr, tr, rhor, a)
            rhor2 = 0.27 * pr / (tr * z2)
            error1 = z2 - z
            #drhor1 = rhor2 - rhor
            z = z2
            
            z2 = Eq2p7(pr, tr, rhor2, a)
            error2 = z2 - z
            drhor2 = rhor2 - rhor
            m = (error2 - error1) / (drhor2)
            
            ii = 0
            while abs(z2 - z) > 0.0001:
                rhor = rhor2
                z = z2
                error1 = error2
                rhor2 = (m * rhor2 - error2) / m
                z2 = Eq2p7(pr, tr, rhor2, a)
                
                error2 = z2 - z
                drhor2 = rhor2 - rhor
                m = (error2 - error1) / (drhor2)
            
                ii +=1
                if ii > 100:
                    return("100 Z iterations - halted")
            zout.append(z)
        if single_p:
            return zout[0]
        else:
            return np.array(zout)
    
    # Hall & Yarborough
    def z_hy(p, degf, sg, tc, pc):
        # Using implemention in Whitson Monograph Eqs 3.42 - 3.45
        single_p = False
        if p.size == 1:
            single_p = True
            ps = [p]
        else:
            ps = p.tolist()
        
        zout = []
        for p in ps:
            ppr = p / pc
            tpr = (degf + 460) / tc
            t = 1/tpr
            alpha = 0.06125*t*np.exp(-1.2*(1-t)**2)
            
            def fy(y): # Eq 3.43
                y2 = y**2
                y3 = y**3
                y4 = y**4
                t2 = t**2
                t3 = t**3
                x = -alpha*ppr + (y+y2+y3-y4)/(1-y)**3
                x -= (14.76*t - 9.76*t2 + 4.58 * t3)*y2
                x += (90.7*t - 242.2*t2 + 42.4*t3)*y**(2.18+2.82*t)
                return x
            
            def dfydy(y): # Eq 3.44
                t2 = t**2
                x = (1+4*y+4*y**2-4*y**3+y**4)/(1-y)**4
                x -= (29.52*t - 19.52*t2 + 9.16*t**3)*y
                x += (2.18 + 2.82*t)*(90.7*t - 242.2*t2 + 42.4*t**3)*y**(1.18+2.82*t)
                return x
            
                
            y = 0.001
            f = fy(y)
            i = 0
            while abs(f) > 1e-8:
                i+= 1
                y -= f*dfydy(y)
                f = fy(y)
                if i > 99:
                    print('Hall & Yarborough did not converge')
                    break
            zout.append( alpha * ppr / y)
        if single_p:
            return zout[0]
        else:
            return np.array(zout)
        
    zfuncs = {'LIN': z_lin,
              'DAK': zdak, 
               'HY': z_hy}
        
    return zfuncs[zmethod.name](p, degf, sg, tc, pc) 
    
def ug(p: npt.ArrayLike, sg: float, degf: float, zmethod: z_method=z_method.DAK, cmethod: c_method=c_method.PMC, n2: float = 0, co2: float = 0, h2s: float = 0, tc: float = 0, pc: float = 0)-> np.ndarray:
    """ Returns Gas Viscosity (cP)
        Uses Lee, Gonzalez & Eakin (1966) Correlation using equations 2.14-2.17 from 'Petroleum Reservoir Fluid Property Correlations' by W. McCain et al.

          p: Gas pressure (psia)
          sg: Gas SG relative to air
          degf: Reservoir Temperature (deg F).  
          zmethod: Method for calculating Z-Factor
                   'LIN' A linearized form (a bit faster) using https://link.springer.com/article/10.1007/s13202-015-0209-3,
                   'DAK' Dranchuk & Abou-Kassem (1975) using from Equations 2.7-2.8 from 'Petroleum Reservoir Fluid Property Correlations' by W. McCain et al.
                   'HY' Hall & Yarborough (1973)
                   defaults to 'DAK' if not specified
          cmethod: Method for calculting critical properties
                   'SUT' for Sutton with Wichert & Aziz non-hydrocarbon corrections, or 
                   'PMC' for Piper, McCain & Corredor (1999) correlation, using equations 2.4 - 2.6 from 'Petroleum Reservoir Fluid Property Correlations' by W. McCain et al.
                   Defaults to 'PMC'
          tc: Critical gas temperature (deg R). Calculates using cmethod if not specified
          pc: Critical gas pressure (psia). Calculates using cmethod if not specified
          n2: Molar fraction of Nitrogen. Defaults to zero if undefined 
          co2: Molar fraction of CO2. Defaults to zero if undefined  
          h2s: Molar fraction of H2S. Defaults to zero if undefined  
    """ 
    p = np.asarray(p) 
    if type(zmethod)==str:
        try:
            zmethod = z_method[zmethod.upper()]
        except:
            print('Incorrect zmethod specified')
            sys.exit()
    if type(cmethod)==str:
        try:
            cmethod = c_method[cmethod.upper()]
        except:
            print('Incorrect cmethod specified')
            sys.exit()
              
    zee = gas_z(p=p, sg=sg, degf=degf, zmethod = zmethod, cmethod=cmethod, tc=tc, pc=pc, n2 = n2, co2 = co2, h2s = h2s)
    t = degf + 460
    m = 28.97 * sg
    rho = m * p / (t * zee * 10.732 * 62.37)
    b = 3.448 + (986.4 / t) + (0.01009 * m) # 2.16
    c = 2.447 - (0.2224 * b) # 2.17
    a = (9.379 + (0.01607 * m)) * np.power(t, 1.5) / (209.2 + (19.26 * m) + t) #2.15
    return a * 0.0001 * np.exp(b * np.power(rho, c)) # 2.14   
    
def ugz(p: npt.ArrayLike, sg: float, degf: float, zee: npt.ArrayLike)-> np.ndarray:
    """ Returns product of Gas Viscosity (cP) * Gas Z-Factor
        With equations 2.14-2.17 from 'Petroleum Reservoir Fluid Property Correlations' by W. McCain et al.
        Same as ug function, but with a precalculated Z factor to eliminate duplicated evaluation in m(p) calculations
        p: Gas pressure (psia)
        degf: Gas Temperature (deg F)
        sg: Specific gravity of reservoir gas (relative to air)
        zee: pre-calculated gas Z-Factor
    """  
    p, zee = np.asarray(p), np.asarray(zee)      
    t = degf + 460
    m = 28.97 * sg
    rho = m * p / (t * zee * 10.732 * 62.37)
    b = 3.448 + (986.4 / t) + (0.01009 * m) # 2.16
    c = 2.447 - (0.2224 * b) # 2.17
    a = (9.379 + (0.01607 * m)) * np.power(t, 1.5) / (209.2 + (19.26 * m) + t) #2.15
    return a * 0.0001 * np.exp(b * np.power(rho, c))*zee # 2.14   

def cg(p: npt.ArrayLike, sg: float, degf: float, n2: float = 0, co2: float = 0, h2s: float = 0, tc: float = 0, pc: float = 0)-> np.ndarray:
    """ Returns gas compressibility (1/psi) using the 'DAK' Dranchuk & Abou-Kassem (1975) Z-Factor &
        Piper, McCain & Corredor (1999) correlation for critical properties (if not specified)
        p: Gas pressure (psia)
        sg: Gas SG relative to air. Defaults to False if undefined
        pwf: BHFP (psia)
        degf: Gas Temperature (deg F)
        
        tc: Critical gas temperature (deg R). Uses cmethod correlation if not specified
        pc: Critical gas pressure (psia). Uses cmethod correlation if not specified
        n2: Molar fraction of Nitrogen. Defaults to zero if undefined 
        co2: Molar fraction of CO2. Defaults to zero if undefined  
        h2s: Molar fraction of H2S. Defaults to zero if undefined 
    """  
    p = np.asarray(p)
    tc, pc = gas_tc_pc(sg=sg, n2=n2, co2=co2, h2s=h2s, tc=tc, pc=pc, cmethod='PMC')
    pr = p / pc
    tr = (degf + 460) / tc
    zee = gas_z(p=p, degf=degf, sg=sg, tc=tc, pc=pc, n2 = n2, co2 = co2, h2s = h2s)
    
    a = [0, 0.3265, -1.07, -0.5339, 0.01569, -0.05165, 0.5475, -0.7361, 0.1844, 0.1056, 0.6134, 0.7210]
    rhor = 0.27 * pr / (tr * zee)
    dzdrho = a[1] + (a[2] / tr) + (a[3] / (tr * tr * tr)) + (a[4] / (tr * tr * tr * tr)) + (a[5] / np.power(tr, 5))
    dzdrho = dzdrho + (2 * rhor * (a[6] + (a[7] / tr) + (a[8] / (tr * tr))))
    dzdrho = dzdrho - (5 * np.power(rhor, 4) * a[9] * ((a[7] / tr) + (a[8] / (tr * tr))))
    dzdrho = dzdrho + (2 * a[10] * rhor / (tr * tr * tr)) * (1 + (a[11] * rhor * rhor) - (a[11] * a[11] * np.power(rhor, 4))) * np.exp(-a[11] * rhor * rhor) # 2.23
    cpr = (1 / pr) - ((0.27 / (zee * zee * tr)) * (dzdrho / (1 + (rhor / zee) * dzdrho))) # 2.22
    cg = cpr / pc # 2.21
    return cg
    
def OneonBg(p: npt.ArrayLike, sg: float, degf: float, zmethod: z_method=z_method.DAK, cmethod: c_method=c_method.PMC, n2: float = 0, co2: float = 0, h2s: float = 0, tc: float = 0, pc: float = 0)-> np.ndarray:
    """ Returns 1/Bg (reciprocal formation volume factor) for natural gas (scf/rcf)
        zmethod: Method for calculating Z-Factor
                 'LIN' A linearized form (a bit faster) using https://link.springer.com/article/10.1007/s13202-015-0209-3,
                 'DAK' Dranchuk & Abou-Kassem (1975) using from Equations 2.7-2.8 from 'Petroleum Reservoir Fluid Property Correlations' by W. McCain et al.
                 'HY' Hall & Yarborough (1973)
                 defaults to 'DAK' if not specified
        cmethod: Method for calculting critical properties
                 'SUT' for Sutton with Wichert & Aziz non-hydrocarbon corrections, or 
                 'PMC' for Piper, McCain & Corredor (1999) correlation, using equations 2.4 - 2.6 from 'Petroleum Reservoir Fluid Property Correlations' by W. McCain et al.
                 Defaults to 'PMC'
          p: Gas pressure (psia)
          tc: Critical gas temperature (deg R). Calculates using cmethod if not specified
          pc: Critical gas pressure (psia). Calculates using cmethod if not specified
          n2: Molar fraction of Nitrogen. Defaults to zero if undefined 
          co2: Molar fraction of CO2. Defaults to zero if undefined  
          h2s: Molar fraction of H2S. Defaults to zero if undefined   
          sg: Gas SG relative to air
          degf: Reservoir Temperature (deg F) 
    """
    p = np.asarray(p)
    if type(zmethod)==str:
        try:
            zmethod = z_method[zmethod.upper()]
        except:
            print('Incorrect zmethod specified')
            sys.exit()
    if type(cmethod)==str:
        try:
            cmethod = c_method[cmethod.upper()]
        except:
            print('Incorrect cmethod specified')
            sys.exit()
            
    zee = gas_z(p=p, degf=degf, sg=sg, tc=tc, pc=pc, n2=n2, co2=co2, h2s=h2s, zmethod=zmethod)
    return 1 / (zee * (degf + 460) / (p * 35.37))

def gas_den(p: npt.ArrayLike, sg: float, degf: float, zmethod: z_method=z_method.DAK, cmethod: c_method=c_method.PMC, n2: float = 0, co2: float = 0, h2s: float = 0, tc: float = 0, pc: float = 0)-> np.ndarray:
    """ Returns gas density for natural gas (lb/cuft)
        
        **kwargs: Optional keywords
          zmethod: Method for calculating Z-Factor
                   'LIN' A linearized form (a bit faster) using https://link.springer.com/article/10.1007/s13202-015-0209-3,
                   'DAK' Dranchuk & Abou-Kassem (1975) using from Equations 2.7-2.8 from 'Petroleum Reservoir Fluid Property Correlations' by W. McCain et al.
                   'HY' Hall & Yarborough (1973)
                   defaults to 'DAK' if not specified
          cmethod: Method for calculting critical properties
                   'sut' for Sutton with Wichert & Aziz non-hydrocarbon corrections, or 
                   'pmc' for Piper, McCain & Corredor (1999) correlation, using equations 2.4 - 2.6 from 'Petroleum Reservoir Fluid Property Correlations' by W. McCain et al.
                   Defaults to 'pmc'
          p: Gas pressure (psia)
          tc: Critical gas temperature (deg R). Calculates using cmethod if not specified
          pc: Critical gas pressure (psia). Calculates using cmethod if not specified
          n2: Molar fraction of Nitrogen. Defaults to zero if undefined 
          co2: Molar fraction of CO2. Defaults to zero if undefined  
          h2s: Molar fraction of H2S. Defaults to zero if undefined
          sg: Gas SG relative to air, Defaults to False if undefined
          degf: Reservoir Temperature (deg F). Defaults to False if undefined 
    """
    p = np.asarray(p)
    if type(zmethod)==str:
        try:
            zmethod = z_method[zmethod.upper()]
        except:
            print('Incorrect zmethod specified')
            sys.exit()
    if type(cmethod)==str:
        try:
            cmethod = c_method[cmethod.upper()]
        except:
            print('Incorrect cmethod specified')
            sys.exit()
            
    zee = gas_z(p=p, degf=degf, sg=sg, tc=tc, pc=pc, n2=n2, co2=co2, h2s=h2s, zmethod=zmethod)
    m = sg * 28.97
    t = degf + 460
    r = 10.732
    rhog = p * m / (zee * r * t)
    return rhog

def PonZ2P(poverz: npt.ArrayLike, sg: float, degf: float, zmethod: z_method=z_method.DAK, cmethod: c_method=c_method.PMC, n2: float = 0, co2: float = 0, h2s: float = 0, tc: float = 0, pc: float = 0, rtol: float = 0.0000001)-> np.ndarray:
    """ Returns pressure corresponding to a P/Z value for natural gas (psia)
        Calculated through iterative solution method
        poverz: Gas pressure / Z-Factor (psia)
        
        zmethod: Method for calculating Z-Factor
                 'LIN' A linearized form (a bit faster) using https://link.springer.com/article/10.1007/s13202-015-0209-3,
                 'DAK' Dranchuk & Abou-Kassem (1975) using from Equations 2.7-2.8 from 'Petroleum Reservoir Fluid Property Correlations' by W. McCain et al.
                 'HY' Hall & Yarborough (1973)
                 defaults to 'DAK' if not specified
        cmethod: Method for calculting critical properties
                 'SUT' for Sutton with Wichert & Aziz non-hydrocarbon corrections, or 
                 'PMC' for Piper, McCain & Corredor (1999) correlation, using equations 2.4 - 2.6 from 'Petroleum Reservoir Fluid Property Correlations' by W. McCain et al.
                 Defaults to 'PMC'
          tc: Critical gas temperature (deg R). Calculates using cmethod if not specified
          pc: Critical gas pressure (psia). Calculates using cmethod if not specified
          n2: Molar fraction of Nitrogen. Defaults to zero if undefined 
          co2: Molar fraction of CO2. Defaults to zero if undefined  
          h2s: Molar fraction of H2S. Defaults to zero if undefined
          sg: Gas SG relative to air, Defaults to False if undefined
          degf: Reservoir Temperature (deg F). Defaults to False if undefined 
          rtol: Relative solution tolerance. Will iterate until abs[(poverz - calculation)/poverz] < rtol
    """
    def PonZ2P_err(args, p):
        ponz, sg, t, zmethod, tc, pc, n2, co2, h2s = args
        zee = gas_z(p=p, degf=t, sg=sg, tc=tc, pc=pc, n2=n2, co2=co2, h2s=h2s, zmethod=zmethod)
        return (p - (ponz * zee))/p
    
    if type(zmethod)==str:
        try:
            zmethod = z_method[zmethod.upper()]
        except:
            print('Incorrect zmethod specified')
            sys.exit()
    if type(cmethod)==str:
        try:
            cmethod = c_method[cmethod.upper()]
        except:
            print('Incorrect cmethod specified')
            sys.exit()
            
    poverz = np.asarray(poverz)
    single_p = False
    if poverz.size == 1:
        single_p = True
        poverz = [poverz]
    else:
        poverz = poverz.tolist()

    p = []
    for ponz in poverz:
        args = (ponz, sg, degf, zmethod, tc, pc, n2, co2, h2s)
        p.append(bisect_solve(args, PonZ2P_err, ponz*0.2, ponz*1.8, rtol))
    p = np.array(p)
    if single_p:
        p = p[0]
    return p
    
def deltamp(p1: float, p2: float, degf: float, sg: float, zmethod: z_method=z_method.DAK, cmethod: c_method=c_method.PMC, n2: float = 0, co2: float = 0, h2s: float = 0, tc: float = 0, pc: float = 0)-> float:
    """ Numerical integration of real-gas pseudopressure between two pressures
        Returns integral over range between p1 to p2 (psi**2/cP)
        p1: Starting (lower) pressure (psia)
        p2: Ending (upper) pressure (psia)
        t: Gas Temperature (deg F)
        sg: Specific gravity of  gas (relative to air)
        zmethod: Method for calculating Z-Factor
                   'LIN' A linearized form (a bit faster) using https://link.springer.com/article/10.1007/s13202-015-0209-3,
                   'DAK' Dranchuk & Abou-Kassem (1975) using from Equations 2.7-2.8 from 'Petroleum Reservoir Fluid Property Correlations' by W. McCain et al.
                   'HY' Hall & Yarborough (1973)
                   defaults to 'DAK' if not specified
        cmethod: Method for calculting critical properties
                 'sut' for Sutton with Wichert & Aziz non-hydrocarbon corrections, or 
                 'pmc' for Piper, McCain & Corredor (1999) correlation, using equations 2.4 - 2.6 from 'Petroleum Reservoir Fluid Property Correlations' by W. McCain et al.
                 Defaults to 'pmc'
        tc: Critical gas temperature (deg R). Calculates using cmethod if not specified
        pc: Critical gas pressure (psia). Calculates using cmethod if not specified
        n2: Molar fraction of Nitrogen. Defaults to zero if undefined 
        co2: Molar fraction of CO2. Defaults to zero if undefined  
        h2s: Molar fraction of H2S. Defaults to zero if undefined 
    """
    def m_p(p, *args):
        # Pseudo pressure function to be integrated
        degf, sg, zmethod, cmethod, tc, pc, n2, co2, h2s = args
        zee = gas_z(p=p, degf=degf, sg=sg, zmethod=zmethod, cmethod=cmethod, n2=n2, co2=co2, h2s=h2s, tc=tc, pc=pc)
        mugz = ugz(p, degf, sg, zee) # Gas viscosity z-factor product using a precalculated Z factor
        return  2 * p / (mugz)
    if type(zmethod)==str:
        try:
            zmethod = z_method[zmethod.upper()]
        except:
            print('Incorrect zmethod specified')
            sys.exit()
    if type(cmethod)==str:
        try:
            cmethod = c_method[cmethod.upper()]
        except:
            print('Incorrect cmethod specified')
            sys.exit()
            
    return quad(m_p, p1, p2, args = (degf, sg, zmethod, cmethod, tc, pc, n2, co2, h2s),limit=500)[0]

def oil_rate_radial(k: npt.ArrayLike, h: npt.ArrayLike, pr: npt.ArrayLike, pwf: npt.ArrayLike, r_w: float, r_ext: float, uo: float, bo: float, S: float=0, vogel: bool=False, pb: float=0)-> np.ndarray:
    """ Returns liquid rate for radial flow (stb/day) using Darcy pseudo steady state equation
        k: Effective Permeability to flow (mD)
        h: Net flow height (ft)
        Pr: Reservoir pressure (psia)
        pwf: BHFP (psia)
        r_w: Wellbore Radius (ft)
        r_ext: External Reservoir Radius (ft)
        S: Wellbore Skin (Dimensionless). Defaults to zero if not specified
        uo: Liquid viscosity (cP)
        bo: Liquid Formation Volume Factor (rb/stb)
        pb: Bubble point pressure (psia). Defaults to zero if not specified. Not used unless Vogel option is invoked
        vogel: (True / False). Invokes the Vogel model that reduces inflow below bubble point pressure. Defaults to False if undefined
    """
    k, h, pr, pwf = np.asarray(k), np.asarray(h), np.asarray(pr), np.asarray(pwf)

    if pb > pr:
        pb = pr # Bubble point pressure can't be above reservoir pressure
    J = 0.00708 * k * h / (uo * bo * (np.log(r_ext / r_w) + S - 0.75)) # Productivity index
    if not vogel:
        qoil = J * (pr - pwf)
    else:
        if pwf >= pb:
            qoil = J * (pr - pwf)  # if producing above Pb, using Darcy
        else: # if below, use simple Vogel relationship correction
            qsat_max = J * pb / 1.8
            qusat = J * (pr - pb)
            qoil = qsat_max * (1 - 0.2 * (pwf / pb) - 0.8 * (pwf / pb) * (pwf / pb)) + qusat
    return qoil   

def oil_rate_linear(k: npt.ArrayLike, h: npt.ArrayLike, pr: npt.ArrayLike, pwf: npt.ArrayLike, width: float, length: float, uo: float, bo: float, vogel: bool=False, pb: float=0)-> np.ndarray:
    """ Returns liquid rate for linear flow (stb/day) using Darcy steady state equation
        k: Permeability (mD)
        h: Net flow height (ft)
        Pr: Reservoir pressure (psia)
        pwf: BHFP (psia)
        width: Width of flow area (ft). Width * Height = Area to flow
        length: Length over which flow takes place (ft)
        uo: Liquid viscosity (cP)
        bo: Liquid Formation Volume Factor (rb/stb)
        pb: Bubble point pressure (psia). Defaults to zero if not specified. Not used unless Vogel option is invoked
        vogel: (True / False). Invokes the Vogel model that reduces inflow below bubble point pressure. Defaults to False if undefined
    """
    k, h, pr, pwf = np.asarray(k), np.asarray(h), np.asarray(pr), np.asarray(pwf)
    
    if pb > pr:
        pb = pr # Bubble point pressure can't be above reservoir pressure
    J = 0.00708 * k * h * width / (2* np.pi * uo * bo * length) # Productivity index
    if not vogel:
        qoil = J * (pr - pwf)
    else:
        if pwf >= pb:
            qoil = J * (pr - pwf)  # if producing above Pb, using Darcy
        else: # if below, use simple Vogel relationship correction
            qsat_max = J * pb / 1.8
            qusat = J * (pr - pb)
            qoil = qsat_max * (1 - 0.2 * (pwf / pb) - 0.8 * (pwf / pb) * (pwf / pb)) + qusat
    return qoil   
    
def Ja_SG(mw: float, Ja: float) -> float:
    """ Returns liquid hydrocarbon specific gravity using Jacoby Aromaticity Factor relationship
        mw: Molecular weight of the liquid (g/gmole / lb/lb.mol)
        Ja: Varies between 0 (Paraffins) - 1 (Aromatic)n
    """
    Ja = min(1, Ja)
    Ja = max(0, Ja)
    return 0.8468 - 15.8/mw + Ja*(0.2456 - 1.77/mw)
    
def twu_liq_props(MW: float, Ja: float = 0, SG: float = 0, Damp: float = 1) -> tuple:
    """ Returns tuple of Tb, Tc, Vc, Pc using method from Twu (1984) correlations for petroleum liquids
        Modified with damping factor proposed by A. Zick between 0 (paraffin) and 1 (original Twu)
        Returns SG, Tb (R), Tc (R), Pc (psia), Vc (ft3/lbmol)
        
        MW: Molecular weight of the liquid hydrocarbon (g/g.mol / lb/lb.mol)
        Ja: Jacoby Aromaticity Factor relationship. Varies between 0 (Paraffins) - 1 (Aromatic). Defaults to zero if undefined
        SG: Specific gravity of the liquid (fraction relative to water density). Will use Jacoby method to estimate SG from MW if undefined.
        Damp: damping factor proposed by A. Zick between 0 (paraffin) and 1 (original Twu). Defaults to 1
        Unless otherwise mentioned, all Twu equation references
        are from Whitson Monograph
    """
    if SG == 0:
        SG = Ja_SG(MW, Ja) # Use Jacoby relationship to estimate SG if not specified

    
    # Estimate boiling point given MW, SG and Paraffinicity
    # Damp = 0 (Paraffin) - 1 (Original Twu)
    # Return boiling point (deg R) and Paraffin properties
    def Twu_Tb(MW, SG, Damp = 1):
        Mp_guess = MW # Guess for paraffinic MW
        Tb, Tcp, Pcp, Vcp, SGp = paraffin_props(Mp_guess)
        d_err = MW - M(Tb, SGp, SG, Mp_guess, Damp)
        n_iter = 0
        while abs(d_err / MW) > 0.0001:
            n_iter +=1
            Mp_guess += d_err
            Tb, Tcp, Pcp, Vcp, SGp = paraffin_props(Mp_guess)
            d_err = MW - M(Tb, SGp, SG, Mp_guess, Damp)
            if n_iter > 100:
                print('Check inputs. Twu algorithm did not converge')
                break
        return Tb, Mp_guess, Tcp, Pcp, Vcp, SGp
    
    # Return MW from modified Eq 5.78 to take into account damping
    def M(Tb, SGp, SG, Mp, Damp):
        absx = abs(0.012342 - 0.328086 / Tb ** 0.5) # Just above Eq 5.78
        dSGM = np.exp(5 * (SGp - SG)) - 1           # Modified Eq 5.78 to take into account damping
        fm = dSGM * (absx + (-0.0175691 + 0.193168 / Tb ** 0.5) * dSGM)  # Just above Eq 5.78
        M = np.exp(np.log(Mp) * (1 + 8 * Damp * fm / (1 - 2 * fm) ** 2)) # Modified Eq 5.78 to take into account damping
        return M
    
    def Twu_Tc(Tb, SGp, SG): 
        Tcp = Tb * (0.533272 + 0.000191017 * Tb + 0.0000000779681 * Tb ** 2 - 2.84376E-11 * Tb ** 3 + 95.9468 / (0.01 * Tb) ** 13) ** -1 # Eq 5.67
        dSGT = np.exp(5 * (SGp - SG)) - 1 # Eq 5.75
        ft = dSGT * ((-0.362456 / Tb ** 0.5) + (0.0398285 - (0.948125 / Tb ** 0.5)) * dSGT) # Eq 5.75
        Tc = Tcp * ((1 + 2 * ft) / (1 - 2 * ft)) ** 2 # Eq 5.75
        return Tc
    
    def Twu_Vc(Tb, Tcp, SG, SGp):
        alpha = 1 - Tb/Tcp # Eq 5.72
        Vcp = (1 - (0.419869 - 0.505839 * alpha - 1.56436 * alpha ** 3 - 9481.7 * alpha ** 14)) ** -8 # Eq 5.69
        dSGV = np.exp(4 * (SGp ** 2 - SG ** 2)) - 1 # Eq 5.76
        f_v = dSGV * ((0.46659 / Tb ** 0.5) + (-0.182421 + (3.01721 / Tb ** 0.5)) * dSGV)  # Eq 5.76
        Vc = Vcp * ((1 + 2 * f_v) / (1 - 2 * f_v)) ** 2  # Eq 5.76
        return Vc
    
    def Twu_Pc(Tb, SGp, SG, Pcp, Tc, Tcp, Vc, Vcp):
        dSGp = np.exp(0.5 * (SGp - SG)) - 1 # Eq 5.77
        fp = dSGp * ((2.53262 - 46.1955 / Tb ** 0.5 - 0.00127885 * Tb) + (-11.4277 + 252.14 / Tb ** 0.5 + 0.00230533 * Tb) * dSGp) # Eq 5.77
        Pc = Pcp * (Tc / Tcp) * (Vcp / Vc) * ((1 + 2 * fp) / (1 - 2 * fp)) ** 2 # Eq 5.77
        return Pc
    
    def paraffin_props(Mp):
        theta = np.log(Mp) # Eq 5.73
        Tb = np.exp(5.71419 + 2.71579 * theta - 0.28659 * theta ** 2 - 39.8544 / theta - 0.122488 / theta ** 2) - 24.7522 * theta + 35.3155 * theta ** 2 # Eq 5.71
        Tcp = Tb * (0.533272 + 0.000191017 * Tb + 0.0000000779681 * Tb ** 2 - 2.84376E-11 * Tb ** 3 + 95.9468 / (0.01 * Tb) ** 13) ** -1 # Eq. 5.67
        alpha = 1 - Tb / Tcp # Eq 5.72
        Pcp = (3.83354 + 1.19629 * alpha ** 0.5 + 34.8888 * alpha + 36.1952 * alpha ** 2 + 104.193 * alpha ** 4) ** 2 # Eq 5.68
        Vcp = (1 - (0.419869 - 0.505839 * alpha - 1.56436 * alpha ** 3 - 9481.7 * alpha ** 14)) ** -8 # Eq 5.69
        SGp = 0.843593 - 0.128624 * alpha - 3.36159 * alpha ** 3 - 13749.5 * alpha ** 12 # Eq 5.70
        return Tb, Tcp, Pcp, Vcp, SGp
     
    Tb, Mp, Tcp, Pcp, Vcp, SGp = Twu_Tb(MW, SG, Damp)
    Tc = Twu_Tc(Tb, SGp, SG)
    Vc = Twu_Vc(Tb, Tcp, SG, SGp)
    Pc = Twu_Pc(Tb, SGp, SG, Pcp, Tc, Tcp, Vc, Vcp)
    return (SG, Tb, Tc, Pc, Vc)

def SG_res_gas(p: float, degf: float, rsb: float, api: float, sg_sp: float) -> float:
    """ Returns estimated specific gravity of gas evolved from oil insitu due to depressurization below Pb
        uses McCain & Hill Correlation (1995, SPE 30773)
        Note: In case of initial free gas cap, you will need to appropriately average gas compositions to reflect
        aggregate insitu free gas specific gravity
        
        p: Pressure (psia)
        degf: Temperature (deg F)
        rsb: Oil solution GOR at Pb (scf/stb)
        api: Stock tank oil density (API)
        sg_sp: Specific gravity of separator gas (relative to air)
    """
        
    if p > 314.7: # Two different sets from original 1995 paper (not reflected in Correlations book)
        a = [0, -208.0797, 22885, -0.000063641, 3.38346, -0.000992, -0.000081147, -0.001956, 1.081956, 0.394035]
    else:
        a = [0, -214.0887, 9971, -0.001303, 3.12715, -0.001495, -0.000085243, -0.003667, 1.47156, 0.714002]
    one_on_sgr = a[1]/p + a[2]/p**2 + a[3]*p + a[4]/degf**0.5 + a[5]*degf + a[6]*rsb + a[7]*api + a[8]/sg_sp + a[9]*sg_sp**2 # Eq 3.25
    return max(1/one_on_sgr, sg_sp)

def Rv(sg_res: float, sg_sp: float, api: float) -> float:
    """ 
     Estimates vaporized condensate volume insitu from difference between insitu and separator gas specific gravities 
     along with the condensate API with simple material balance.
     Returns stb/mmscf separator gas
     
     sg_res: Specific gravity of reservoir gas (relative to air)
     sg_sep: Specific gravity of separator gas (relative to air)
     api: Density of condensate (API)
     """
    
    sep_moles = 1 # 1 Mole separator gas basis
    raw_moles = sep_moles * sg_res / sg_sp # Raw gas moles
    shrinkage = sep_moles / raw_moles
    raw_gas_mass = sg_res*28.97*raw_moles   # lb-moles
    sep_gas_mass = sg_sp*28.97*sep_moles    # lb-moles
    cond_mass = raw_gas_mass - sep_gas_mass # lb-moles
    cond_sg = 141.4 / (api+131.5)
    cond_vol = cond_mass/(cond_sg*62.4)     # cuft
    return cond_vol / 5.61458 / sep_moles   # stb/mmscf of separator gas
    
def SG_st_gas(psp: float, rsp: float, api: float, sg_sp: float, degf_sp: float) -> float:
    """ Estimates specific gravity of gas evolving from stock tank
        from oil API and separator gas properties & conditions
        Returns sg_st (Stock Tank SG relative to air). 
        Correlation reproduced from Valko McCain 2003 paper Eq 4-2
        
        psp: Separator pressure (psia)
        rsp: Separator GOR (separator scf / stb)
        api: Stock tank oil density (API)
        sg_sp: Separator gas specific gravity relative to air
        degf_sp: Separator temperature (deg f)
    """
    var = [np.log(psp), np.log(rsp), api, sg_sp, degf_sp]
    C = [[-17.275, -0.3354, 3.705, -155.52, 2.085], 
         [7.9597, -0.3346, -0.4273, 629.61, -7.097e-2],
         [-1.1013, 0.1956, 1.818e-2, -957.38, 9.859e-4],
         [2.7735e-2, -3.4374e-2, -3.459e-4, 647.57, -6.312e-6],
         [3.2287e-3, 2.08e-3, 2.505e-6, -163.26, 1.4e-8]]
    Zn = [sum([C[i][n]*var[n]**i for i in range(5)]) for n in range(5)]
    Z = sum(Zn)
    sg_st = 1.219 + 0.198 * Z + 0.0845 * Z**2 + 0.03 * Z**3 + 0.003 * Z**4
    return sg_st
    
def SG_surf_gas(sg_sp: float, rsp: float, sg_st: float, rst: float) -> float:
    """ Calculates weighted average specific gravity of surface gas
        separator and stock tank properties
        Returns sg_g (Weighted average surface gas SG relative to air). 
        From McCain Correlations book, Eq 3.4
        
        sg_sp: Separator gas specific gravity relative to air
        rsp: Separator GOR (separator scf / stb)
        sg_st: Stock tank gas specific gravity relative to air
        rst: Stock tank producing gas-oil ratio (scf/stb)
    """
    sg_g = (sg_sp*rsp + sg_st*rst)/(rsp+rst)
    return sg_g

def Rs_st(psp: float, degf_sp: float, api: float) -> float:
    """ Estimates incremental stock tank producing gas-oil ratio (scf/stb) from separator measurements
        Rsb = Rsp + Rst (Solution GOR at bubble point = Separator GOR + Stock Tank GOR). 
        In absence of separator properties, a simple linear relationship with Rsp could be used instead;
          rs_st = 0.1618 * Separator GOR (Adapted from Eq 3-4 in Valko McCain 2003 paper)
        Correlation reproduced from Valko McCain 2003 paper Eq 3-2
        
        psp: Separator pressure (psia)
        degf_sp: Separator temperature (deg f)
        api: Stock tank oil density (API)
    """
    var = [np.log(psp), np.log(degf_sp), api]
    C = [[-8.005, 1.224, -1.587], 
         [2.7, -0.5, 0.0441],
         [-0.161, 0, -2.29e-5]]
    Zn = [sum([C[i][n]*var[n]**i for i in range(3)]) for n in range(3)]
    Z = sum(Zn)
    rs_st = max(0,3.955 + 0.83 * Z - 0.024 * Z**2 + 0.075 * Z**3)
    return rs_st
    
def pbub(api: float, degf: float, rsb: float, sg_g: float=0, sg_sp: float=0, pbmethod: pb_method=pb_method.VALMC) -> float:
    """ Returns bubble point pressure (psia) calculated from different correlations
        
        api: Stock tank oil density (deg API)
        degf: Reservoir Temperature (deg F)
        rsb: Oil solution gas volume at Pbub (scf/stb)
        pbmethod: A string or pb_method Enum class that specifies one of following calculation choices;
                   STAN: Standing Correlation (1947)
                   VALMC: Valko-McCain Correlation (2003) - https://www.sciencedirect.com/science/article/abs/pii/S0920410502003194
                   VELAR: Velarde, Blasingame & McCain (1997) - Default
        sg_sp: Separator Gas specific Gravity (relative to air) <-- Required for Valko McCain & Velarde
        sg_g: Weighted average specific gravity of surface gas (relative to air). <-- Required for Standing
    """    
    if type(pbmethod)==str:
        try:
            pbmethod = pb_method[pbmethod.upper()]
        except:
            print('Incorrect pbmethod specified')
            sys.exit()
            
    if pbmethod.name == 'STAN':
        if rsb*api*sg_g*degf == 0:
            print('Need valid values for rs, api, sg_g for Standing Pb calculation')
            print('Need valid values for rs, api, sg_g and degf for Standing or Velarde Pb calculation')
            sys.exit()
    else:
        if rsb*api*sg_sp*degf == 0:
            print(rsb,api,sg_sp,degf)
            print('Need valid values for rsb, api, sg_sp and degf for Velarde or Valko McCain Pb calculation')
            sys.exit()
                    
    def pbub_standing(api, degf, sg_g, rsb, sg_sp) -> float:
        a = 0.00091*degf - 0.0125*api
        return 18.2*((rsb/sg_g)**0.83*10**a-1.4)
        
    def pbub_valko_mccain(api, degf, sg_g, rsb, sg_sp) -> float:
        if rsb <=0:
            return pbub_velarde(api, degf, sg_g, 0, sg_sp)
        var = [np.log(rsb), api, sg_sp, degf]
        C = [[-5.48, 1.27, 4.51, -0.7835], 
             [-0.0378, -0.0449, -10.84, 6.23e-3],
             [0.281, 4.36e-4, 8.39, -1.22e-5],
             [-0.0206, -4.76e-6, -2.34, 1.03e-8]]
        Zn = [sum([C[i][n]*var[n]**i for i in range(4)]) for n in range(4)]
        Z = sum(Zn)
        lnpb = 7.475+0.713*Z + 0.0075*Z**2
        return np.exp(lnpb)
    
    def pbub_velarde(api, degf, sg_g, rsb, sg_sp) -> float: 
        x = 0.013098*degf**0.282372-8.2e-6*api**2.176124
        pbp = 1091.47*(rsb**0.081465*sg_sp**-0.161488*10**x-0.740152)**5.354891
        return pbp
    
    fn_dic = {'STAN': pbub_standing,
              'VALMC': pbub_valko_mccain,
              'VELAR': pbub_velarde}
    
    return fn_dic[pbmethod.name](api=api, degf=degf, sg_g=sg_g, rsb=rsb, sg_sp=sg_sp)

def Rsbub(api: float, degf: float, pb: float, sg_g: float=0, sg_sp: float=0, pbmethod: pb_method=pb_method.VALMC) -> float:
    """ Returns Solution GOR (scf/stb) at bubble point pressure.
        Uses the inverse of the Bubble point pressure correlations, with the same method families
        Note: At low pressures, the VALMC method will fail (generally when Rsb < 10 scf/stb).
              The VALMC method will revert to the VELAR method in these cases
        
        api: Stock tank oil density (deg API)
        degf: Reservoir Temperature (deg F)
        pb: Bubble point Pressure (psia)
        pbmethod: A string or pb_method Enum class that specifies one of following calculation choices;
                   STAN: Standing Correlation (1947)
                   VALMC: Valko-McCain Correlation (2003) - Default
                   VELAR: Velarde, Blasingame & McCain (1997) 
        sg_sp: Separator Gas specific Gravity (relative to air) <-- Required for Valko McCain & Velarde
        sg_g: Weighted average specific gravity of surface gas (relative to air). <-- Required for Standing
    """
    if sg_sp == 0:
        sg_sp = sg_g
    if sg_g == 0:
        sg_g = sg_sp
        
    if type(pbmethod)==str:
        try:
            pbmethod = pb_method[pbmethod.upper()]
        except:
            print('Incorrect pbmethod specified')
            sys.exit()
            
    if pbmethod.name == 'STAN':
        if pb*api*sg_g*degf == 0:
            print('Need valid values for pb, api, sg_g for Standing Correlation')
            sys.exit()
    else:
        if pb*api*sg_sp*degf == 0:
            print('Need valid values for pb, api, sg_sp and degf for Velarde or Valko McCain Pb calculation')
            sys.exit()
                    
    def rsbub_standing(api, degf, pb, sg_g, sg_sp) -> float:
        a = 0.00091*degf - 0.0125*api
        lnrsbub = np.log((pb/18.2 +1.4)/10**a) / 0.83 + np.log(sg_g)
        rsbub = np.exp(lnrsbub)
        return rsb
        
    def rsbub_valko_mccain(api, degf, pb, sg_g, sg_sp) -> float:
        # Solve via iteration. First guess using Velarde Rsb, then simple Newton Iterations
        rsb = rsbub_velarde(api, degf, pb, sg_g, sg_sp)
        i = 0
        pbcalc = 0
        while abs(pb-pbcalc) > 1e-5:
            i += 1
            pbcalc = pbub(degf = degf, api = api, sg_sp = sg_g, rsb=rsb, pbmethod=pbmethod)
            dpbdrsb = pbub(degf = degf, api = api, sg_sp = sg_g, rsb=rsb+0.5, pbmethod=pbmethod)-pbub(degf = degf, api = api, sg_sp = sg_g, rsb=rsb-0.5, pbmethod=pbmethod)
            try:
                rsb = rsb -  (pbcalc - pb)/dpbdrsb
            except:
                rsbub_velarde(api, degf, pb, sg_g, sg_sp)
            if i > 100: # At low rsb VALMC will not converge, use Velarde instead
                return rsbub_velarde(api, degf, pb, sg_g, sg_sp)
        return rsb
        
    def rsbub_velarde(api, degf, pb, sg_g, sg_sp) -> float: 
        x = 0.013098*degf**0.282372-8.2e-6*api**2.176124
        rsb = (0.270811* sg_sp**(10093/62500)* pb**0.186745 *10**(-x) + 92519* sg_sp**(10093/62500)* 2**(-x - 3)* 5**(-x - 6))**(200000/16293)
        return max(rsb,0)
    
    fn_dic = {'STAN': rsbub_standing,
              'VALMC': rsbub_valko_mccain,
              'VELAR': rsbub_velarde}
    
    rsbub = fn_dic[pbmethod.name](api=api, degf=degf, pb=pb, sg_g=sg_g, sg_sp=sg_sp)
    if np.isnan(rsbub):
        return 0
    else:
        return rsbub
    
def Rs(api: float, degf: float, sg_sp: float, p: float = 0, pb: float=0, rsb: float=0, rsp: float=0, degf_sep: float = 80, p_sep: float = 114.7, rsmethod: rs_method=rs_method.VELAR) -> float:
    """ Returns solution gas oil ratio (scf/stb) calculated from different correlations
        
        api: Stock tank oil density (deg API)
        degf: Reservoir Temperature (deg F)
        rsmethod: A string or pb_method Enum class that specifies one of following calculation choices;
                   VELAR: Velarde, Blasingame & McCain (1999) - Default
                   STAN: Standing Correlation (1947), using form from https://www.sciencedirect.com/science/article/pii/B9780128034378000014
                   VASBG: Vasquez & Beggs Correlation (1984)

        rsb: Oil solution gas volume at bubblepoint pressure (scf/stb) <-- Required for Velarde, Blasingame & McCain
        rsp: Separator produced GOR (scf separator gas / STB oil) <-- Required for Velarde, Blasingame & McCain
        sg_sp: Separator Gas specific Gravity (relative to air)
        pb: Bubble point pressure (Used only for Velarde, Blasingame & McCain). If not provided, will attempt to calculate with Valko-McCain Pb Correlation
        p: Reservoir pressure (psia)
        degf_sep: Separator temperature (deg F) - Required for Vasquez & Beggs. Defaults to 80 deg F if not defined
        p_sep: Separator pressure (psia) - Required for Vasquez & Beggs. Defaults to 114.7 psia if not defined
    """
    
    if type(rsmethod)==str:
        try:
            rsmethod = rs_method[rsmethod.upper()]
        except:
            print('Incorrect rsmethod specified')
            sys.exit()
    
    def Rs_velarde(api, degf, sg_sp, p, pb, rsb, rsp, degf_sep, p_sep):  # Velarde, Blasingame & McCain (1997)  
        # Velarde, Blasingame & McCain (1999)
        # Equations 3.8a - 3.8f
        # Estimates Rs of depleting oil from separator oil observations
        if sg_sp * api * rsb == 0:
            print('Missing one of the required inputs: sg_sp, api, rsb, for the Velarde, Blasingame & McCain Rs calculation')
            sys.exit()
        A = [9.73e-7, 1.672608, 0.929870, 0.247235, 1.056052]
        B = [0.022339, -1.004750, 0.337711, 0.132795, 0.302065]
        C = [0.725167, -1.485480, -0.164741, -0.091330, 0.047094]

        if pb==0: # Calculate Pb
            if rsb*sg_sp == 0:
                print('Need to either specifiy pb, or provide values for rsp and sg_sp so Pb can be estimated with VALMC method')
                sys.exit()
            pb = pbub(api=api, degf=degf, rsb=rsb, sg_sp=sg_sp, pbmethod='VALMC')
        xs = [A, B, C]
        a = [x[0]*sg_sp**x[1]*api**x[2]*degf**x[3]*(pb-14.7)**x[4] for x in xs]
        pr = (p-14.7)/(pb-14.7)
        rsr = a[0]*pr**a[1]+(1-a[0])*pr**a[2]
        rs = rsb * rsr
        return rs
    
    def Rs_standing(api, degf, sg_sp, p, pb, rsb, rsp, degf_sep, p_sep):
        a = 0.00091*degf - 0.0125*api # Eq 1.64
        return sg_sp*((p/18.2+1.4)*10**-a)**(1.2048) # Eq 1.72
    
    def Rs_vasquezbegs(api, degf, sg_sp, p, pb, rsb, rsp, degf_sep, p_sep):
        sg_gs = sg_sp*(1+5.912e-5*api*degf_sep*np.log10(p_sep/114.7)) # Gas sg normalized to 100 psig separator conditions
        if api <= 30:
            return 0.0362*sg_gs*p**1.0937*np.exp(25.7240*(api/(degf+460)))
        else:
            return 0.0178*sg_gs*p**1.1870*np.exp(23.9310*(api/(degf+460)))

    fn_dic = {'VELAR': Rs_velarde,
              'STAN': Rs_standing,
              'VASBG': Rs_vasquezbegs}

    return fn_dic[rsmethod.name](api=api, degf=degf, sg_sp=sg_sp, p=p, pb=pb, rsb=rsb, rsp=rsp, degf_sep=degf_sep, p_sep=p_sep)

def Co(p: float, rs: float, api: float,  degf: float, sg_sp: float=0, sg_g: float=0, pb: float=0, rsb: float=0, pi: float=0, comethod: co_method=co_method.SPIV, zmethod: z_method=z_method.DAK):
    """ Returns oil compressibility (1/psi) calculated with Spivey correlation at pressures > Pbub
         and McCain correlations for Bo and Rs below Pb, with Co = -1/Bo *[dBodp - Bg*dRsdp]
        
        api: Stock tank oil density (deg API)
        sg_sp: Separator Gas specific Gravity (relative to air). If not defined, will use sg_g instead
        sg_g: Weighted average specific gravity of surface gas (relative to air). If not defined, will use sg_sp instead
        degf: Reservoir Temperature (deg F)
        pb: Bubble point pressure. If not provided, will attempt to calculate with Valko-McCain Pb Correlation
        rsb: Oil solution gas volume at bubblepoint pressure (scf/stb)
        comethod: A string or co_method Enum class that specifies one of following calculation choices;
                  SPIV: Spivey, Valko & McCain (2007) - Default - https://onepetro.org/REE/article-abstract/10/01/43/196779/Applications-of-the-Coefficient-of-Isothermal
        zmethod: Method for calculating Z-Factor
                 'LIN' A linearized form (a bit faster) using https://link.springer.com/article/10.1007/s13202-015-0209-3,
                 'DAK' Dranchuk & Abou-Kassem (1975) using from Equations 2.7-2.8 from 'Petroleum Reservoir Fluid Property Correlations' by W. McCain et al.
                 'HY' Hall & Yarborough (1973)
                 defaults to 'DAK' if not specified
        
        sg_g: Weighted average specific gravity of surface gas (relative to air).     
        p: Reservoir pressure (psia)
        pi: Initial reservoir pressure (psia). Must be specified for Spivey method above bubble point
    """
    
    def Co_spivey(p, rs, api, sg_sp, sg_g, degf, pb, rsb, pi, zmethod): #(2007) From McCain book
        def co_p_gte_pb(p, rs, api, sg_sp, degf, pb, rsb, pi, zmethod):    
            sg_o = 141.4 / (api+131.5)
            C = [[3.011, -0.0835, 3.51, 0.327, -1.918, 2.52],
                 [-2.6254, -0.259, -0.0289, -0.608, -0.642, -2.73],
                 [0.497, 0.382, -0.0584, 0.0911, 0.154, 0.429]]
            var = [np.log(api), np.log(sg_sp), np.log(pb), np.log(p/pb), np.log(rsb), np.log(degf)]

            Zn = [sum([C[i][n]*var[n]**i for i in range(3)]) for n in range(6)]
            Zp = sum(Zn)
            ln_cofb_p = 2.434 + 0.475*Zp + 0.048*Zp**2 - np.log(10**6)# - np.log(10**6) # 3.13a. Note, Ln(10e6) was not in original paper
            cofb_p = np.exp(ln_cofb_p)
            
            # Recalculate at initial reservoir pressure
            var_pi = [np.log(api), np.log(sg_sp), np.log(pb), np.log(pi/pb), np.log(rsb), np.log(degf)]
            Zn_pi = [sum([C[i][n]*var_pi[n]**i for i in range(3)]) for n in range(6)] # 3.13c
            Z_pi = sum(Zn_pi) # 3.13b
            ln_cofb_pi = 2.434 + 0.475*Z_pi + 0.048*Z_pi**2 - np.log(10**6)# - np.log(10**6) # 3.13a. Note, Ln(10e6) was not in original paper
            cofb_pi = np.exp(ln_cofb_pi)

            cofi = ((p-pb)*cofb_p-(pi-pb)*cofb_pi)/(p-pi) # 3.14
            dZdp = (-0.608+0.1822*np.log(p/pb))/p # 3.15c
            dcofbdp = cofb_p*(0.475+0.096*Zp)*dZdp # 3.15b
            co = cofb_p+(p-pb)*dcofbdp # 3.15a
            return co
        
        def co_p_lt_pb(p, rs, api, sg_sp, sg_g, degf, pb, rsb, pi, zmethod):
            sg_o = 141.4 / (api+131.5)
            rhoa = 38.52*10**(-0.00326*api)+(94.75-33.93*np.log(api))*np.log(sg_g) #3.17e
            
            A = [9.73e-7, 1.672608, 0.929870, 0.247235, 1.056052]
            B = [0.022339, -1.004750, 0.337711, 0.132795, 0.302065]
            C = [0.725167, -1.485480, -0.164741, -0.091330, 0.047094]
            xs = [A, B, C]
                        
            a = [x[0]*sg_sp**x[1]*api**x[2]*degf**x[3]*(pb-14.7)**x[4] for x in xs]
            pr = (p-14.7)/(pb-14.7)
            
            drsdp = rsb*(a[0]*a[1]*pr**(a[1]-1)+(1-a[0])*a[2]*pr**(a[2]-1))/(pb-14.7) # 3.17a
            rho_or = Deno(p=p, degf=degf, rs=rs, sg_g=sg_g, sg_sp=sg_sp, pb=pb, sg_o=sg_o, api=api, denomethod='SWMH') 
            rhoa = 38.52*10**(-0.00326*api)+(94.75-33.93*np.log(api))*np.log(sg_g) # 3.17e
            drhopodp = sg_g*drsdp*((73.71-4600*sg_o/rhoa)/((73.71+rs*sg_g/rhoa)**2)) # 3.17d
            rhopo = (rsb*sg_g+4600*sg_o)/(73.71+rsb*sg_g/rhoa) # Eq 3.18b
            ddeltarhopdp = 10e-3*(0.167+16.181*10**(-0.0425*rhopo))-10e-3*(1.5835*(10**-0.0425*rhopo)*p*drhopodp)-10e-8*(0.598*p+526*p*10**(-0.0603*rhopo)) + 10e-8*(36.52*p**2*(10**-0.0603*rhopo)*drhopodp) # Eq 3.17f
            drhobsdp = drhopodp + ddeltarhopdp # Eq 3.17h
            deltarhop = (0.167 + 16.181*(10**-0.0425*rhopo))*(pb/1000) - 0.01*(0.299+263*(10**-0.0603*rhopo))*(pb/1000)**2 # Eq 3.18e
            rhobs = rhopo + deltarhop # Eq 3.18f
            ddeltarhotdp = (-1.4313*rhobs**-1.951*(degf -60)**0.938 - 0.0008638*(10**-0.0161*rhobs))*(degf-60)**0.475*drhobsdp # Eq 3.17g
            drhoordp = drhopodp + ddeltarhopdp - ddeltarhotdp # Eq 3.17c
            dbodp = 1/(rho_or**2)*(0.01357*sg_g*rho_or*drsdp-(sg_o*64.37+0.01357*rs*sg_g)*drhoordp) # 3.17b
            
            sg_r = SG_res_gas(p=p, degf=degf, rsb=rs, api=api, sg_sp=sg_sp) # Reservoir gas density
            bg = 1/OneonBg(p=p, sg=sg_g, degf=degf)
            bo = Bo(p, pb, degf, rs, sg_sp, sg_g, sg_o)
            print(bg, bo)
            co = -1/bo*(dbodp - bg*drsdp)
            return co

        if p < pb:
            return co_p_lt_pb(p, rs, api, sg_sp, sg_g, degf, pb, rsb, pi, zmethod)
        else:
            return co_p_gte_pb(p, rs, api, sg_sp, sg_g, degf, pb, rsb, pi, zmethod)
    
    def Co_vasquez_beggs(): # Vasquez and Beggs
        pass   
        
    if pb <= 0: # Calculate Pb if not provided
        if rs * api* sg_sp* degf == 0:
            print('Missing one of the required inputs to estimate Pb: rsp, api, sg_sp, degf')
            sys.exit()
        pb = pbub(api=api, degf=degf, sg_g=sg_g, rsb=rsb, sg_sp=sg_sp)
  
    if type(comethod)==str:
        try:
            comethod = co_method[comethod.upper()]
        except:
            print('Incorrect copressibility comethod specified')
            sys.exit()
            
    fn_dic = {'SPIV': Co_spivey,
              'VASBG': Co_vasquez_beggs}
    
    if comethod.name in fn_dic:
        return fn_dic[comethod.name](p=p, rs=rs, api=api, sg_sp=sg_sp, sg_g=sg_g, degf=degf, pb=pb, rsb=rsb, pi=pi, zmethod=zmethod)
    else:
        print('co_method parameter not properly set')
        
def Deno(p: float, degf:float, rs:float, rsb:float, sg_g: float = 0, sg_sp: float = 0, pb: float = 1e6, sg_o:float=0, api:float=0, denomethod: deno_method=deno_method.SWMH) -> float:
    """ Returns live oil density calculated with different correlations
        
        p: Pressure (psia)
        pb: Bubble point pressure (psia). Defaults to 1E6, and not used for densities below Pb. A valid value is required for density calculations above Pb
        degf: Reservoir Temperature (deg F)
        rs: Oil solution gas volume (scf/stb)
        rsb: Oil solution gas volume at bubble point pressure (scf/stb)
        sg_g: Weighted average specific gravity of surface gas (relative to air).  
        sg_sp: Separator gas specific gravity (relative to air). If not known, an alternate nethod to estimate pseudo liquid density of surface gas will be used
        sg_o: Stock tank oil specific gravity (SG relative to water). If undefined will calculate from api
        api: Stock tank oil density (deg API). If undefined will calculate from sg_o. If both defined api value will prevail
        denomethod: A string or deno_method Enum class that specifies one of following calculation choices;
                   SWMH: Standing, White, McCain-Hill (1995) - Default
    """
    if sg_g == 0 and sg_sp == 0:
        print('Must define at least one of sg_g and sg_sp for density calculation')
        sys.exit()

    # Density at or below initial bubble point pressure
    def Deno_standing_white_mccainhill(p: float, degf:float, rs:float, rsb:float, sg_g: float,sg_sp: float, pb: float, sg_o:float, api:float) -> float: # (1995), Eq 3.18a - 3.18g
        if sg_sp > 0:
            a = np.array([-49.8930, 85.0149, -3.70373, 0.0479818, 2.98914, -0.0356888])
            rho_po = 52.8 - 0.01*rs # First estimate
            err = 1
            i = 0
            while err > 1e-8:
                i+= 1
                rhoa = a[0]+a[1]*sg_sp+a[2]*sg_sp*rho_po+a[3]*sg_sp*rho_po**2+a[4]*rho_po+a[5]*rho_po**2 # Eq 3.18c
                new_rho_po = (rs*sg_sp+4600*sg_o)/(73.71+rs*sg_sp/rhoa) # pseudoliquid density, Eq 3.18b. Note equation in origiganl paper uses sg_sp rather than sg_g as in book.
                err= abs(rho_po-new_rho_po)
                rho_po = new_rho_po
                if i > 100:
                    break
        else:
            rhoa = 38.52*(10**(-0.00326*api))+(94.75-33.93*np.log10(api))*np.log10(sg_g)  # Eq 3.17e using sg_g. Apparent liquid density of surface gases
            rho_po = (rs*sg_g+4600*sg_o)/(73.71+rs*sg_g/rhoa) # pseudoliquid density, Eq 3.18b
        
        drho_p = (0.167+16.181*10**(-0.0425*rho_po))*p/1000 - 0.01*(0.299+263*10**(-0.0603*rho_po))*(p/1000)**2 # Eq 3.19d
        rho_bs = rho_po + drho_p # fake density used in calculations, Eq 3.19e
        drho_t = (0.00302+1.505*rho_bs**-0.951)*(degf-60)**0.938-(0.0216-0.0233*10**(-0.0161*rho_bs))*(degf-60)**0.475
        rho_or = rho_bs - drho_t
        return rho_or
    
    def Deno_p_gt_pb(p: float, degf: float, rs: float, rsb:float, sg_g: float, sg_sp: float, pb: float, sg_o: float, api:float) -> float:
        rhorb = Deno_standing_white_mccainhill(p=p, degf=degf, rs=rs, rsb=rsb, sg_g=sg_g, sg_sp=sg_sp, pb=pb, sg_o=sg_o, api=api)
        
        # cofb calculation from default compressibility algorithm
        C = [[3.011, -0.0835, 3.51, 0.327, -1.918, 2.52],
             [-2.6254, -0.259, -0.0289, -0.608, -0.642, -2.73],
             [0.497, 0.382, -0.0584, 0.0911, 0.154, 0.429]]
        var = [np.log(api), np.log(sg_sp), np.log(pb), np.log(p/pb), np.log(rsb), np.log(degf)]
        Zn = [sum([C[i][n]*var[n]**i for i in range(3)]) for n in range(6)]
        Zp = sum(Zn)
        ln_cofb_p = 2.434 + 0.475*Zp + 0.048*Zp**2 - np.log(10**6)
        cofb_p = np.exp(ln_cofb_p)
        
        return rhorb * np.exp(cofb_p*(p-pb)) # Eq 3.20
    
             
    fn_dic = {'SWMH': Deno_standing_white_mccainhill,
              'PGTPB': Deno_p_gt_pb} # Pressure greater than Pb
    
    if type(denomethod)==str:
        try:
            denomethod = deno_method[denomethod.upper()]
        except:
            print('Incorrect denomethod specified')
            sys.exit()
    
    if api == 0 and sg_o == 0:
        print('Must supply either sg_o or api')
        sys.exit()
    
    if api == 0: # Set api from sg_o
        api = 141.5/sg_o -131.5
    else:        # overwrite sg_o with api value
        sg_o = 141.4 / (api+131.5)
    
    if p > pb: # Use Eq 3.20, calculating oil density from density at Pb and compressibility factor
        return fn_dic['PGTPB'](p=p, degf=degf, rs=rs, rsb = rsb, sg_g=sg_g, sg_sp=sg_sp, pb=pb, sg_o=sg_o, api=api)
    
    return fn_dic[denomethod.name](p=p, degf=degf, rs=rs, rsb = rsb, sg_g=sg_g, sg_sp=sg_sp, pb=pb, sg_o=sg_o, api=api)
        
def Bo(p:float, pb: float, degf: float, rs:float , sg_g:float, sg_sp: float, sg_o:float, bomethod: bo_method=bo_method.VELAR) -> float:
    
    def Bo_standing(p, pb, degf, rs, sg_sp, sg_g, sg_o):
        return 0.972 + 1.47e-4*(rs*(sg_g/sg_o)**0.5+1.25*degf)**1.175
    
    def Bo_velarde(p, pb, degf, rs, sg_sp, sg_g, sg_o):
        rhor = Deno(p=p, degf=degf, rs=rs, rsb=rs, sg_g=sg_g, sg_sp=sg_sp, pb=pb, sg_o=sg_o, denomethod='SWMH')
        return (sg_o*62.372+0.013357*rs*sg_g)/rhor            
    
    fn_dic = {'STAN': Bo_standing,
              'VELAR': Bo_velarde}

    if type(bomethod)==str:
        try:
            bomethod = bo_method[bomethod.upper()]
        except:
            print('Incorrect bomethod specified')
            sys.exit()
    
    return fn_dic[bomethod.name](p, pb, degf, rs, sg_sp, sg_g, sg_o)

def viso(p: float, api: float, degf: float, pb: float, rs: float) -> float:
    """ Returns Oil Viscosity with Beggs-Robinson (1975) correlation at saturated pressures
        and Petrosky-Farshad (1995) at undersaturated pressures
        
        p: Pressure (psia)
        api: Stock tank oil density (deg API)
        degf: Reservoir Temperature (deg F)
        pb: Bubble point Pressure (psia)
        rs: Solution GOR (scf/stb)
    """
    
    def uo_br(p, api, degf, pb, rs):
        Z = 3.0324 - 0.02023 * api
        y = 10**Z
        X = y*degf**-1.163
        A = 10.715*(rs+100)**-0.515
        B = 5.44*(rs+150)**-0.338
        
        uod = 10**X - 1 
        uor = A*uod**B # Eq 3.23c
        return uor
    
    def uo_pf(p, api, degf, pb, rs):
        uob = uo_br(pb, api, degf, pb, rs)
        loguob = np.log(uob)
        A = -1.0146+1.3322*loguob-0.4876*loguob**2 - 1.15036*loguob**3 # Eq 3.24b
        uor = uob + 1.3449e-3*(p-pb)*10**A # Eq 3.24a
        return uor
        
    if p <= pb:
        return uo_br(p, api, degf, pb, rs)
    else:
        return uo_pf(p, api, degf, pb, rs)

def make_bot(pi: float, api: float, degf: float, sg_g: float, pmax: float, pb: float=0, rsb: float=0, pmin: float=14.7, nrows: int = 20, wt: float=0, ch4_sat: float=0) -> tuple:
    """
    Returns tuple of results (BOT Pandas Table, ST Oil Density (lb/cuft), ST Gas Density (lb/cuft), Water Density at Pi (lb/cuft), Water Compressibility at Pi (1/psi), Water Viscosity at Pi (cP))
    If user species Pb or Rsb only, the corresponding property will be calculated
    If both Pb and Rsb are specified, then Pb calculations will be adjusted to honor both
    
    pi: Initial reservoir pressure (psia). Used to return water properties at initial pressure
    pb: Bubble point pressure (psia)
    rsb: Oil solution GOR at Pb (scf/stb)
    degf: Reservoir Temperature (deg F)
    sg_g: Weighted average specific gravity of surface gas (relative to air).  
    api: Stock tank oil density (deg API).
    pmax: Maximum pressure to calcuate table to
    pmin: Minimum pressure to calculate table to. Default = 14.7
    nrows: Number of BOT rows. Default = 20
    wt: Salt wt% (0-100). Default = 0
    ch4_sat: Degree of methane saturation (0 - 1). Default = 0
    """
    sg_o = 141.4 / (api+131.5)
    rsb_frac = 1.0
    if rsb <= 0 and pb > 0:
        rsb = Rsbub(degf = degf, api = api, sg_sp = sg_g, pb = pb, pbmethod='VALMC')
    elif pb <=0 and rsb > 0:
        pb = pbub(degf = degf, api = api, sg_sp = sg_g, rsb=rsb, pbmethod='VALMC')
    else: # Need to estimate Rs fraction to honor Pbub given by user
        pbcalc = pbub(degf = degf, api = api, sg_sp = sg_g, rsb=rsb, pbmethod='VALMC')
        err = 100
        rsb_old = rsb
        i = 0
        while err > 0.01:
            rsbnew = pb/pbcalc * rsb_old
            pbcalc = pbub(degf = degf, api = api, sg_sp = sg_g, rsb=rsbnew, pbmethod='VALMC')
            rsb_old = rsbnew
            err = abs(pb - pbcalc)
            i += 1
            if i > 100:
                print('Could not solve Pb & Rsb for these combination of inputs')
                sys.exit()
        rsb_frac = rsbnew / rsb
  
    pbi = pb
    sg_sp = sg_g
    drows = 3
    if pmin in [pb, pi]:
        drows -=1
    if pmax in [pb, pi]:
        drows -= 1
    if pb == pi:
        drows -= 1
        
    incr = (pmax-pmin)/(nrows-drows)
    
    pressures = list(np.arange(pmin, pmax+incr, incr))
    pressures.append(pbi)
    pressures.append(pi)
    pressures = list(set(pressures))
    pressures.sort()
    pressures = np.array(pressures)
    rss, bos, uos, gfvf, visg, gz, rvs, sg_rs, bws, visws = [[] for x in range(10)]
    
    for p in pressures:
        if p > pbi:
            pb = pbi
            rss.append(rsb)
        else:
            pb = p
            if len(rss)>1:
                if rss[-1] >10:
                    rss.append(Rsbub(degf = degf, api = api, sg_sp = sg_g, pb = pb, pbmethod='VALMC')/rsb_frac)
                else:
                    rss.append(Rsbub(degf = degf, api = api, sg_sp = sg_g, pb = pb, pbmethod='VELAR')/rsb_frac)
            else:
                rss.append(Rsbub(degf = degf, api = api, sg_sp = sg_g, pb = pb, pbmethod='VALMC')/rsb_frac)
                    
        bos.append(Bo(p=p, pb=pbi, degf=degf, rs=rss[-1], sg_g=sg_g, sg_sp=sg_g, sg_o=sg_o))
        uos.append(viso(p=p, api=api, degf=degf, pb=pb, rs=rss[-1]))
        gfvf.append(1/OneonBg(p=p, sg=sg_sp, degf=degf)*1000/5.61458) # rb/mscf
        gz.append(gas_z(p=p, sg=sg_sp, degf=degf)) 
        visg.append(ug(p=p, sg=sg_sp, degf=degf))
        bw, lden, visw, cw, rsw = brine_props(p=p, degf=degf, wt=wt, ch4_sat=ch4_sat)
        bws.append(bw)
        visws.append(visw)
    
    st_deno = sg_o * 62.4 # lb/cuft
    st_deng = gas_den(p=14.7, sg=sg_sp, degf=60)
    bw, lden, visw, cw, rsw = brine_props(p=pi, degf=degf, wt=wt, ch4_sat=ch4_sat)
    res_denw = lden * 62.4 # lb/cuft
    res_cw = cw
    df = pd.DataFrame()
    df['Pressure (psia)'] = pressures
    df['Rs (scf/stb)'] = rss
    df['Bo (rb/stb)'] = bos
    df['uo (cP)'] = uos
    df['Gas Z (v/v)'] = gz
    df['Bg (rb/mscf'] = gfvf
    df['ug (cP)'] = visg
    df['Bw (rb/stb)'] = bws
    df['uw (cP)'] = visws
    return (df, st_deno, st_deng, res_denw, res_cw, visw)
                  
def saturated_water_content(p: float, degf: float) -> float:
    """ Returns saturated volume of water vapor in natural gas (stb/mmscf)
        From 'PVT and Phase Behaviour Of Petroleum Reservoir Fluids' by Ali Danesh 
        degf: Water Temperature (deg F)
        p: Water pressure (psia)
    """
    t = degf
    content = (47484 * (np.exp(69.103501 + (-13064.76 / (t + 460)) + (-7.3037 * np.log(t + 460)) + (0.0000012856 * ((t + 460) * (t + 460))))) / (p) + (np.power(10, ((-3083.87 / (t + 460)) + 6.69449)))) * (1 - (0.00492 * 0) - (0.00017672 * (0 * 0))) / 8.32 / 42
    return content

def brine_props(p: float, degf: float, wt: float, ch4_sat: float) -> tuple:
    """ Calculates Brine properties from modified Spivey Correlation per McCain Petroleum Reservoir Fluid Properties pg 160
        Returns tuple of (Bw (rb/stb), Density (sg), viscosity (cP), Compressibility (1/psi))
        p: Pressure (psia)
        degf: Temperature (deg F)
        wt: Salt wt% (0-100)
        ch4_sat: Degree of methane saturation (0 - 1)  
    """
    
    def Eq41(t,input_array): # From McCain Petroleum Reservoir Fluid Properties
        t2 = t/100
        return (input_array[1]*t2**2+input_array[2]*t2+input_array[3])/(input_array[4]*t2**2+input_array[5]*t2+1)

    Mpa = p*0.00689476 # Pressure in mPa
    degc = (degf-32)/1.8  # Temperature in deg C
    degk = degc+273  # Temperature in deg K
    m = 1000*(wt/100)/(58.4428*(1-(wt/100))) # Molar concentration of NaCl from wt % in gram mol/kg water

    rhow_t70_arr = [0, -0.127213, 0.645486, 1.03265, -0.070291, 0.639589]
    Ewt_arr = [0, 4.221, -3.478, 6.221, 0.5182, -0.4405]
    Fwt_arr = [0, -11.403, 29.932, 27.952, 0.20684, 0.3768]
    Dm2t_arr = [0, -0.00011149, 0.000175105, -0.00043766, 0, 0]
    Dm32t_arr = [0, -0.0008878, -0.0001388, -0.00296318, 0, 0.51103]
    Dm1t_arr = [0, 0.0021466, 0.012427, 0.042648, -0.081009, 0.525417]
    Dm12t_arr = [0, 0.0002356, -0.0003636, -0.0002278, 0, 0]
    Emt_arr = [0, 0, 0, 0.1249, 0, 0]
    Fm32t_arr = [0, -0.617, -0.747, -0.4339, 0, 10.26]
    Fm1t_arr = [0, 0, 9.917, 5.1128, 0, 3.892]
    Fm12t_arr = [0, 0.0365, -0.0369, 0, 0, 0]

    rhow_t70 = Eq41(degc,rhow_t70_arr)
    Ewt = Eq41(degc,Ewt_arr)
    Fwt = Eq41(degc,Fwt_arr)
    Dm2t = Eq41(degc,Dm2t_arr)
    Dm32t = Eq41(degc,Dm32t_arr)
    Dm1t = Eq41(degc,Dm1t_arr)
    Dm12t = Eq41(degc,Dm12t_arr)
    Emt = Eq41(degc,Emt_arr)
    Fm32t = Eq41(degc,Fm32t_arr)
    Fm1t = Eq41(degc,Fm1t_arr)
    Fm12t = Eq41(degc,Fm12t_arr)

    cwtp = (1/70)*(1/(Ewt*(Mpa/70)+Fwt)) # Eq 4.2

    Iwt70 = (1/Ewt)*np.log(abs(Ewt+Fwt))  # Eq 4.3
    Iwtp = (1/Ewt)*np.log(abs(Ewt*(Mpa/70)+Fwt)) # Eq 4.4
    rhowtp = rhow_t70*np.exp(Iwtp-Iwt70)  # Eq 4.5
    
    rhobt70 = rhow_t70+Dm2t*m*m+Dm32t*m**1.5+Dm1t*m+Dm12t*m**0.5 # Eq 4.6
    Ebtm = Ewt+Emt*m # Eq 4.7
    Fbtm = Fwt + Fm32t*m**1.5+Fm1t*m+Fm12t*m**0.5 # Eq 4.8
    cbtpm = (1/70)*(1/(Ebtm*(Mpa/70)+Fbtm))  # Eq 4.9
    Ibt70 = (1/Ebtm)*np.log(abs(Ebtm + Fbtm)) # Eq 4.10
    Ibtpm = (1/Ebtm)*np.log(abs(Ebtm*(Mpa/70) + Fbtm)) # Eq 4.11
    Rhob_tpm = rhobt70*np.exp(Ibtpm-Ibt70) # Eq 4.12 - Density of pure brine (no methane) in SG
    
    # Re-evaluate at standard conditions (15 deg C)
    rhow_sc70 = Eq41(15,rhow_t70_arr)
    Ew_sc = Eq41(15,Ewt_arr)
    Fw_sc = Eq41(15,Fwt_arr)
    Dm2_sc = Eq41(15,Dm2t_arr)
    Dm32_sc = Eq41(15,Dm32t_arr)
    Dm1_sc = Eq41(15,Dm1t_arr)
    Dm12_sc = Eq41(15,Dm12t_arr)
    Em_sc = Eq41(15,Emt_arr)
    Fm32_sc = Eq41(15,Fm32t_arr)
    Fm1_sc = Eq41(15,Fm1t_arr)
    Fm12_sc = Eq41(15,Fm12t_arr)
        
    cw_sc = (1/70)*(1/(Ew_sc*(0.1013/70) + Fw_sc))
    Iw_sc70 = (1/Ew_sc)*np.log(abs(Ew_sc + Fw_sc)) 
    Iw_sc = (1/Ew_sc)*np.log(abs(Ew_sc*(0.1013/70)+Fw_sc))
    rhow_sc = rhow_sc70*np.exp(Iw_sc-Iw_sc70) 
    rhob_sc70 = rhow_sc70+Dm2_sc*m*m+Dm32_sc*m**1.5+Dm1_sc*m+Dm12_sc*m**0.5 
    Eb_scm = Ew_sc+Em_sc*m 
    Fb_scm = Fw_sc + Fm32_sc*m**1.5+Fm1_sc*m+Fm12_sc*m**0.5
    cb_scm = (1/70)*(1/(Eb_scm*(0.1015/70)+Fb_scm)) 
    Ib_sc70 = (1/Eb_scm)*np.log(abs(Eb_scm + Fb_scm)) 
    Ib_scm = (1/Eb_scm)*np.log(abs(Eb_scm*(0.1015/70) + Fb_scm)) 
    Rhob_scm = rhob_sc70*np.exp(Ib_scm-Ib_sc70) # Density of pure brine (no methane) in SG at standard conditions
    
    a_coefic = [0, -7.85951783, 1.84408259, -11.7866497, 22.6807411, -15.9618719, 1.80122502]
    x = 1-(degk/647.096) # Eq 4.14
    ln_vap_ratio = (647.096/degk)*(a_coefic[1]*x + a_coefic[2]*x**1.5 + a_coefic[3]*np.power(x,3) + a_coefic[4]*np.power(x,3.5) + a_coefic[5]*np.power(x,4) + a_coefic[6]*np.power(x,7.5)) # Eq 4.13
    vap_pressure = np.exp(ln_vap_ratio)*22.064
        
    a_coefic = [0, 0, -0.004462, -0.06763, 0, 0]
    b_coefic = [0, -0.03602, 0.18917, 0.97242, 0, 0]
    c_coefic = [0, 0.6855, -3.1992, -3.7968, 0.07711, 0.2229]
        
    A_t = Eq41(degc,a_coefic)
    B_t = Eq41(degc,b_coefic)
    C_t = Eq41(degc,c_coefic)
    
    mch4w = np.exp(A_t*np.power(np.log(Mpa-vap_pressure),2)+B_t*np.log(Mpa-vap_pressure)+C_t)    # Eq 4.15
    u_arr = [0, 8.3143711, -7.2772168e-4, 2.1489858e3, -1.4019672e-5, -6.6743449e5, 7.698589e-2, -5.0253331e-5, -30.092013, 4.8468502e3,0]
    lambda_arr = [0,-0.80898, 1.0827e-3, 183.85,0,0,3.924e-4, 0,0,0,-1.97e-6]
    eta_arr = [0, -3.89e-3,0,0,0,0,0,0,0,0,0]
        
    lambda_ch4Na = lambda_arr[1]+lambda_arr[2]*degk+(lambda_arr[3]/degk)+lambda_arr[6]*Mpa+lambda_arr[10]*Mpa*Mpa
    Eta_ch4Na = eta_arr[1]
    mch4b = mch4w*np.exp(-2*lambda_ch4Na*m-Eta_ch4Na*m*m)    #Eq 4.18 - Methane solubility in brine (g-mol/kg H2O)
    
    mch4 = ch4_sat * mch4b    #    Fraction of saturated methane solubility
        
    dudptm = u_arr[6] + u_arr[7]*degk + (u_arr[8]/degk) + (u_arr[9]/(degk*degk))    # Eq 4.19
    dlambdadptm = lambda_arr[6]+2*lambda_arr[10]*Mpa    # Eq 4.20
    detadptm =     0 # Eq 4.21

    Vmch4b = 8.314467*degk*(dudptm + 2*m*dlambdadptm+m*m*0)     # Eq 4.22
    vb0 = 1/Rhob_tpm    # Eq 4.23
    rhobtpbch4 = (1000+m*58.4428+mch4*16.043)/((1000+m*58.4428)*vb0+(mch4*Vmch4b))    # Eq 4.24... mch4 = Methane concentration in g/cm3
    vbtpbch4 = 1/rhobtpbch4
    dvbdp = -vb0*cbtpm    # Eq 4.27
    d2uch2dp2 = 0
    d2lambdadp2 = 2*lambda_arr[10]
    d2etadp2 = 0
    dVmch4dp = 8.314467*degk*(d2uch2dp2+2*m*d2lambdadp2+m*m*d2etadp2)    #Eq 4.31
    cwu = -((1000+m*58.4428)*dvbdp+mch4*dVmch4dp)/((1000+m*58.4428)*vb0+(mch4*Vmch4b))    # Eq 4.32 -- Undersaturated brine Compressibility (Mpa-1)
    satdmch4dp = mch4*(2*A_t*np.log(Mpa-vap_pressure)+B_t)/((Mpa-vap_pressure)-2*dlambdadptm*m)    # Eq 4.33
        
    zee = gas_z(p=p, sg=0.5537, degf=degf) # Z-Factor of pure methane
    
    vmch4g =zee*8.314467*degk/Mpa #  Eq 4.34
        
    cws = -((1000 + m*58.4428) * dvbdp + mch4 * dVmch4dp + satdmch4dp * (Vmch4b - vmch4g))/((1000 + m*58.4428) * vb0 + ( mch4 * Vmch4b ))        # Eq 4.35 - Compressibility of saturated brine Mpa-1
    cw_new = 1/(145.038*(1/cws))    # Compressibility in psi-1
    vb0_sc = 1/Rhob_scm    # vb0 at standard conditions - (Calculated by evaluating vbo at 0.1013 MPa and 15 degC)
    Bw = (((1000+m*58.4428)*vb0)+(mch4*Vmch4b))/((1000+m*58.4428)*vb0_sc)
        
    zee_sc = gas_z(p=14.7, sg=0.5537, degf=60)
    vmch4g_sc =zee_sc*8.314467*(273+15)/0.1013 #  Eq 4.34
    rsw_new = mch4*vmch4g_sc/((1000+m*58.4428)*vb0_sc)
    rsw_new_oilfield = rsw_new/0.1781076    # Convert to scf/stb
        
    d = [0, 2885310, -11072.577, -9.0834095, 0.030925651, -0.0000274071, -1928385.1, 5621.6046, 13.82725, -0.047609523, 0.000035545041]
    a = [-0.21319213, 0.0013651589, -0.0000012191756]
    b = [0.069161945, -0.00027292263, 0.0000002085244]
    c = [-0.0025988855, 0.0000077989227]
    
    lnuw_tp = sum([d[i] * np.power(degk , (i - 3)) for i in range(1,6)])
    lnuw_tp += sum([rhowtp * (d[i] * np.power(degk, (i - 8))) for i in range(6,11)])
    
    uw_tp = np.exp(lnuw_tp)
    
    AA = a[0] + a[1] * degk + a[2] * degk *degk   # Eq 4.43
    BB = b[0] + b[1] * degk + b[2] * degk * degk
    CC = c[0] + c[1] * degk
    
    lnur_tm = AA * m + BB * m *m + CC * m *m*m # Eq 4.46
    ur_tm = np.exp(lnur_tm)
    ub_tpm = ur_tm * uw_tp * 1000 # cP - Eq 4.48
    
    bw = Bw           # rb/stb
    lden = rhobtpbch4 # sg
    visw = ub_tpm       # cP
    cw = cw_new         # 1/psi
    rsw = rsw_new_oilfield #scf/stb
		 	
    return (bw, lden, visw, cw, rsw)

def Lorenz2B(lorenz: float, lrnz_method: str = 'EXP') -> float:
    """ Returns B-factor that characterizes the Lorenz function
        Lorenz: Lorenz factor (0-1)
        lrnz_method: The method of calculation for the Lorenz factor
                Must be 'EXP' (Exponential) or 'LANG' (Langmuir). 
                Defaults to EXP if undefined
                Background on Exponential formulation can be found in https://www.linkedin.com/pulse/loving-lorenz-new-life-old-parameter-mark-burgoyne/
                For Langmuir formulation; SumKh = Phih * VL / (Phih + PL)
                Lorenz = (VL - PL * VL * np.log(VL) + PL * VL * np.log(PL) - 0.5) * 2
                Where PL = 1 / B and VL = PL + 1
    """
    method = lrnz_method.upper()
    if method != 'EXP' and method != 'LANG':
        print('Method must be "LANG" or "EXP"')
        sys.exit()

    if lorenz < 0.000333:
        B = 2 / 1000
        if method == "LANG":
            B = 1 / 1000
        return B
    if lorenz > 0.997179125528914:
        B = 709
        if method == "LANG":
            B = 25000
        return B

    # Set bookends for B
    hi = 709
    if method == "LANG":
        hi = 25000
    lo = 0.000001
    args = (lorenz, method)
    def LorenzErr(args, B):
        lorenz, method = args
        B = max(B,0.000001)
        if method == 'EXP':
            B = min(B,709)
            err = 2 * ((1 / (np.exp(B) - 1)) - (1 / B)) + 1 - lorenz
        else:
            B = min(B,25000)
            PL = 1 / B
            VL = PL + 1
            err = (VL - PL * VL * np.log(VL) + PL * VL * np.log(PL) - 0.5) * 2 - lorenz
        return err
    rtol = 0.0000001
    return bisect_solve(args, LorenzErr, lo, hi, rtol)

def LorenzFromB(B: float, lrnz_method: str = 'EXP') -> float:
    """ Returns Lorenz factor that corresponds to a Beta value
        B: The B-Factor (positive float)
        lrnz_method: The method of calculation for the Lorenz factor
                Must be 'EXP' or 'LANG'. 
                Defaults to Exponential if undefined
                Background on Exponential formulation can be found in https://www.linkedin.com/pulse/loving-lorenz-new-life-old-parameter-mark-burgoyne/
                For Langmuir formulation; SumKh = Phih * VL / (Phih + PL)
                Lorenz = (VL - PL * VL * np.log(VL) + PL * VL * np.log(PL) - 0.5) * 2
                Where PL = 1 / B and VL = PL + 1
    """
    method = lrnz_method.upper()
    B = max(B, 0.000001)
    if method == 'LANG':
        B = min(B, 25000)
        PL = 1 / B
        VL = PL + 1
        L = (VL - PL * VL * np.log(VL) + PL * VL * np.log(PL) - 0.5) * 2
    else:
        B = min(B,709)
        L = 2 * (1 / (np.exp(B) - 1) - (1 / B)) + 1
    return L

def LorenzFromFlowFraction(kh_frac: float, phih_frac: float, lrnz_method: str = 'EXP') -> float:
    """ Returns Lorenz factor consistent with observed flow fraction from a phi_h fraction
        kh_frac: (0 - 1). Fraction of total flow from best quality reservoir phi_h
        phih_frac: (0 - 1). phi_h fraction that delivers the observed kh_fraction of flow
        lrnz_method: The method of calculation for the Lorenz factor
                Must be 'EXP' or 'LANG'. 
                Defaults to Exponential if undefined
                Background on Exponential formulation can be found in https://www.linkedin.com/pulse/loving-lorenz-new-life-old-parameter-mark-burgoyne/
                For Langmuir formulation; SumKh = Phih * VL / (Phih + PL)
                Lorenz = (VL - PL * VL * np.log(VL) + PL * VL * np.log(PL) - 0.5) * 2
                Where PL = 1 / B and VL = PL + 1
    """
    method = lrnz_method.upper()
    if kh_frac <= phih_frac: # 
        print('kh fraction should always be greater than phi_h fraction')
        return 0.001
    if kh_frac >= 1:
        print("kh Fraction must be less than 1")
        return 0.001
    
    # If Langmuir method, can explicitly calculate B
    if method == 'LANG':
        x = phih_frac
        y = kh_frac
        B = (y - x) / (x * (1 - y))
        return LorenzFromB(B, method)

    # Set bookends and first guess of B
    hi = 709
    lo = 0.000001
    args = (kh_frac, phih_frac, method)
    
    def BErr(args, B):
        kh_frac, phih_frac, method = args
        method = method.upper()
        B = max(B, 0.000001)
        if method == 'EXP':
            B = min(B, 709)
            err = (1 - np.exp(-B * phih_frac)) / (1 - np.exp(-B)) - kh_frac
        else:
            B = min(B, 25000)
            PL = 1 / B
            VL = PL + 1
            err = (VL * phih_frac) / (PL + phih_frac) - kh_frac
        return err
    rtol = 0.0000001
    B = bisect_solve(args, BErr, lo, hi, rtol)
    return LorenzFromB(B, method)

def FlowFrac(phih_frac: npt.ArrayLike, lrnz_method: str = 'EXP', B: float=-1, lorenz: float=-1) -> np.ndarray:
    """ Returns expected flow fraction from the best phi_h fraction, with a sepcified Lorenz factor
        
        phih_frac: (0 - 1). Best phi_h fraction
        lrnz_method: The method of calculation for the Lorenz factor
                Must be 'EXP' or 'LANG'. 
                Defaults to Exponential if undefined
                Background on Exponential formulation can be found in https://www.linkedin.com/pulse/loving-lorenz-new-life-old-parameter-mark-burgoyne/
                For Langmuir formulation; SumKh = Phih * VL / (Phih + PL)
                Lorenz = (VL - PL * VL * np.log(VL) + PL * VL * np.log(PL) - 0.5) * 2
                Where PL = 1 / B and VL = PL + 1
        B: Factor that characterizes the Lorenz function for the given method. Will calculate if only lorenz variable defined
        lorenz: Lorenz factor (0-1). If B is provided, will igonore this parameter to be more efficient. If not, will calculate B from this parameter.
    """
    phih_frac = np.asarray(phih_frac)
    method = lrnz_method.upper()
    if B < 0 and lorenz < 0:
        print('Must define either B or lorenz parameters')
        sys.exit()
    
    if B < 0: # Need to calculate B
        B = Lorenz2B(lorenz=lorenz, lrnz_method=lrnz_method)
        
    B = max(B, 0.000001)
    if method == 'EXP':
        B = min(B, 709)
        fraction = (1 - np.exp(-B * phih_frac)) / (1 - np.exp(-B))
    else:
        B = min(B, 25000)
        PL = 1 / B
        VL = PL + 1
        fraction = (VL * phih_frac) / (PL + phih_frac)
    return fraction

def ix_extract_problem_cells(filename: str='', silent: bool=False) -> list:
    """
    Processes Intersect PRT file to extract convergence issue information
    Prints a summary of worst offenders to terminal (if silent=False), and returns a list
    of sorted dataframes summarising all entities in final convergence row in the PRT files
    List returned is [well_pressure_df, grid_pressure_df, sat_change_df, comp_change_df]
    filename: If empty, will search local directory for PRT file and present list to select from if more than one exists. 
              If a filename is furnished, or only one file exists, then no selection will be presented
    silent: False will return only the list of dataframes, with nothing echoed to the terminal
            True will return summary of worst entities to the terminal
    """
    
    if filename != '': # A Filename has been provided
        if 'PRT' not in filename.upper():
            print('File name needs to be an IX print file with .PRT extension')
            return

    if filename == '': # Show selection in local directory
        prt_files = glob.glob('*.PRT', recursive = False) 
        if len(prt_files) == 0:
            print( 'No .PRT files exist in this directory - Terminating script')
            sys.exit()
        
        if len(prt_files) > 1:
            table = []
            header=['Index', 'PRT File Name']  # Print list of options to select from
            for i in range(len(prt_files)):
                table.append([i,prt_files[i]])
            print(tabulate(table,headers=header))    
            print(' ')
            prt_file_idx = int(input('Please choose index of PRT file to parse (0 - '+str(len(prt_files)-1)+') :'))
    
            if prt_file_idx not in [i for i in range(0, len(prt_files))]:
                print( '\nIndex entered outside range permitted - Terminating script')
                sys.exit()
        else:
            prt_file_idx = 0
            
        filename = prt_files[prt_file_idx]
    
    if not silent:
        print('Processing '+filename+'\n')
    file1 = open(filename, 'r')
    count = 0
    grab_line1 = False
    grab_line2 = False
    max_it = 12
    timesteps = []
    tables = []
    
    while True:
        count += 1
        line = file1.readline()  # Get next line from file
        # if line is empty, end of file is reached
        if not line:
            break
        if 'MaxNewtons                    | Maximum number of nonlinear iterations' in line:
            line = line.split('|')
            max_it = int(line[3])
            continue
        if 'REPORT   Nonlinear convergence at time' in line:
            table = []
            timesteps.append(line.split()[5])
            grab_line1 = True
            continue
        if grab_line1:
            if 'Max' in line:
                grab_line2 = True
                continue
        if grab_line2:
            if '|     |' in line:
                tables.append(table)
                grab_line1, grab_line2 = False, False
                continue
            table.append(line)
    file1.close()
    
    # Parse all the last lines in each table
    well_pressures, grid_pressures, saturations, compositions, scales, balances = [[] for x in range(6)]
    
    for table in tables:
        if len(table) == max_it:
            line = table[-1]
            if '*' not in line: # If within tolerance, skip
                continue
            line = line.split('|')[2:-1]
            
            if '*' in line[0]:
                well_pressures.append(line[0].split())
            if '*' in line[1]:
                grid_pressures.append(line[1].split())
            if '*' in line[2]:
                saturations.append(line[2].split())
            if '*' in line[3]:
                compositions.append(line[3].split())
            if '*' in line[4]:
                scales.append(line[4].split())
            if '*' in line[5]:
                balances.append(line[5].split())
    
    # Summarize bad actors
    def most_frequent(List):
        occurence_count = Counter(List)
        return occurence_count.most_common(1)[0][0]
    
    well_pressure_wells = [x[1] for x in well_pressures]
    grid_pressure_locs = [x[1] for x in grid_pressures]
    saturation_locs = [x[1] for x in saturations]
    composition_locs = [x[1] for x in compositions]
    
    headers = ['Issue Type', 'Total Instances', 'Most Frequent Actor', 'Instances']
    data = [well_pressure_wells, grid_pressure_locs, saturation_locs, composition_locs]
    names = ['Well Pressure Change', 'Grid Pressure Change', 'Grid Saturation Change', 'Grid Composition Change']
    dfs, table, problem_data, problem_data_count = [[] for x in range(4)]
    for d, dat in enumerate(data):
        if len(dat) > 0:
            problem_data.append(most_frequent(dat))
            problem_data_count.append(dat.count(problem_data[-1]))
        else:
            problem_data.append('None')
            problem_data_count.append(0)   
        table.append([names[d], len(dat), problem_data[-1], problem_data_count[-1]])
        dfs.append(pd.DataFrame.from_dict(Counter(dat), orient='index'))

    if not silent:
        print(tabulate(table, headers=headers),'\n')

    for df in dfs:
        try:
            df.columns = ['Count']
            df.sort_values(by='Count', ascending=False, inplace=True)
        except:
            pass
    return dfs

def rel_perm(rows: int, table_type: kr_table=kr_table.SWOF, krfamily: kr_family=kr_family.COR, kromax: float=1, krgmax: float=1, krwmax: float=1, swc: float=0, swcr: float=0, sorg: float=0, sorw: float=0, sgcr: float=0, no: float=1, nw: float=1, ng: float=1, Lw: float=1, Ew: float=1, Tw: float=1, Lo: float=1, Eo: float=1, To: float=1, Lg: float=1, Eg: float=1, Tg: float=1)-> pd.DataFrame:
    """ Returns ECLIPSE styled relative permeability tables
        Users need only define parameters relevant to their table / family selection
        rows: Integer value specifying the number of table rows desired
        table_type: A string or kr_table Enum class that specifies one of three table type choices;
                   SWOF: Water / Oil table
                   SGOF: Gas / Oil table
                   SGFN: Gas / Water table
        krfamily: A string or kr_family Enum class that specifies one of two curve function choices;
                   COR: Corey Curve function
                   LET: LET Relative permeability function
        kromax: Max Kr relative to oil. Default value = 1
        krgmax: Max Kr relative to gas. Default value = 1
        krwmax: Max Kr relative to water. Default value = 1
        swc: Minimum water saturation. Default value = 0
        swcr: Maximum water saturation for imobile water. Default value = 0
        sorg: Maximum oil saturation relative to gas for imobile oil. Default value = 0
        sorw: Maximum oil saturation relative to water for imobile oil. Default value = 0
        sgcr: Maximum gas saturation relative to water for imobile gas. Default value = 0
        no, nw, ng: Corey exponents to oil, wtaer and gas respectively. Default values = 1
        Lw, Ew, Tw: LET exponents to water. Default values = 1
        Lo, Eo, To: LET exponents to oil. Default values = 1
        Lg, Eg, Tg: LET exponents to gas. Default values = 1
    """
    
    if type(table_type)==str:
        try:
            table_type = kr_table[table_type.upper()]
        except:
            print('Incorrect table type specified')
            sys.exit()
    if type(krfamily)==str:
        try:
            krfamily = kr_family[krfamily.upper()]
        except:
            print('Incorrect krfamily specified')
            sys.exit()
            
   
    def kr_SWOF(rows: int, table_type: kr_table=kr_table.SWOF, krfamily: kr_family=kr_family.COR, kromax: float=1, krgmax: float=1, krwmax: float=1, swc: float=0, swcr: float=0, sorg: float=0, sorw: float=0, sgcr: float=0, no: float=1, nw: float=1, ng: float=1, Lw: float=1, Ew: float=1, Tw: float=1, Lo: float=1, Eo: float=1, To: float=1, Lg: float=1, Eg: float=1, Tg: float=1)-> pd.DataFrame:

        if no * nw <= 0: # Not enough information for Corey curves
            corey_info = False
        else:
            corey_info = True
        if Lw * Ew * Tw * Lo * Eo * To <= 0: # Not enough information for LET curves
            let_info = False
        else:
            let_info = True
            
        ndiv = rows
        if swcr > swc:
            ndiv -= 2
        if sorw > 0:
            ndiv -= 1
        ndiv = min(ndiv,rows-1)
            
        sw_eps = [swc, swcr, 1-sorw, 1]
        swn = np.arange(0,1,1/ndiv)
        sw = swn*(1 - swcr - sorw) + swcr
        sw = list(sw) + sw_eps
        sw = list(set(sw))
        sw.sort()
        sw = np.array(sw)
    
        # Assign water relative permeabilities
        swn = (sw - swcr) / (1 - swcr - sorw)
        swn = np.clip(swn, 0, 1)

        if krfamily.name == 'COR':
            if not corey_info:
                print( 'Not enough information for SWOF Corey Curves. Check if no and nw are defined')
                return
            krw = krwmax * swn ** nw
            if sorw > 0:
                krw[-1]=1
        if krfamily.name == 'LET':
            if not let_info:
                print( 'Not enough information for SWOF LET Curves. Check if Lw, Ew, Tw, Lo, Eo & To are defined')
                return
            krw = krwmax*((swn) ** Lw) / (1 + ((swn) ** Lw) + (Ew * ((1 - swn) ** Tw)) - 1)
            if sorw > 0:
                krw[-1]=1
            
        # Assign oil relative permeabilities
        swn = (sw - swc) / (1 - swc - sorw)
        swn = np.clip(swn, 0, 1)
        if krfamily.name == 'COR':
            kro = kromax * (1 - swn) ** no
        if krfamily.name == 'LET':
            kro = kromax*((1 - swn) ** Lo) / (1 + ((1 - swn) ** Lo) + (Eo * (swn ** To)) - 1)
        
        kr_df = pd.DataFrame()
        kr_df['Sw'] = sw
        kr_df['Krwo'] = krw
        kr_df['Krow'] = kro
        return kr_df
    
    def kr_SGOF(rows: int, table_type: kr_table=kr_table.SWOF, krfamily: kr_family=kr_family.COR, kromax: float=1, krgmax: float=1, krwmax: float=1, swc: float=0, swcr: float=0, sorg: float=0, sorw: float=0, sgcr: float=0, no: float=1, nw: float=1, ng: float=1, Lw: float=1, Ew: float=1, Tw: float=1, Lo: float=1, Eo: float=1, To: float=1, Lg: float=1, Eg: float=1, Tg: float=1)-> pd.DataFrame:
           
        if not no * ng: # Not enough information for Corey curves
            corey_info = False
        else:
            corey_info = True
        if not Lg * Eg * Tg * Lo * Eo * To: # Not enough information for LET curves
            let_info = False
        else:
            let_info = True
                
        ndiv = rows
        if sgcr > 0:
            ndiv -= 2
        if sorg > 0:
            ndiv -= 1
        ndiv = min(ndiv,rows-1)
        
        sg_eps = [0, 1 - swc - sorg]
        sgn = np.arange(0,1+1/ndiv,1/ndiv)
        sg = sgn*(1 - swc - sorg)
        sg = list(sg) + sg_eps
        sg = list(set(sg))
        sg.sort()
        sg = np.array(sg)
    
        # Assign gas relative permeabilities
        sgn = sg / (1 - swc - sorg)
        sgn = np.clip(sgn, 0, None)
        if krfamily.name == 'COR':
            if not corey_info:
                print( 'Not enough information for SGOF Corey Curves. Check if no and ng are defined')
                return
            krg = krgmax * sgn ** ng
        if krfamily.name == 'LET':
            if not let_info:
                print( 'Not enough information for SGOF LET Curves. Check if Lg, Eg, Tg, Lo, Eo & To are defined')
                return
            krg = krgmax*((sgn) ** Lg) / (1 + ((sgn) ** Lg) + (Eg * ((1 - sgn) ** Tg)) - 1)

            
        # Assign oil relative permeabilities
        if krfamily.name == 'COR':
            kro = kromax * (1 - sgn) ** no
        if krfamily.name == 'LET':
            kro = kromax*((1 - sgn) ** Lo) / (1 + ((1 - sgn) ** Lo) + (Eo * (sgn ** To)) - 1)
        
        kr_df = pd.DataFrame()
        kr_df['Sg'] = sg
        kr_df['Krgo'] = krg
        kr_df['Krog'] = kro
        return kr_df
          
    def kr_SGWFN(rows: int, table_type: kr_table=kr_table.SWOF, krfamily: kr_family=kr_family.COR, kromax: float=1, krgmax: float=1, krwmax: float=1, swc: float=0, swcr: float=0, sorg: float=0, sorw: float=0, sgcr: float=0, no: float=1, nw: float=1, ng: float=1, Lw: float=1, Ew: float=1, Tw: float=1, Lo: float=1, Eo: float=1, To: float=1, Lg: float=1, Eg: float=1, Tg: float=1)-> pd.DataFrame:
        if ng * nw <= 0: # Not enough information for Corey curves
            corey_info = False
        else:
            corey_info = True
        if Lw * Ew * Tw * Lg * Eg * Tg <= 0: # Not enough information for LET curves
            let_info = False
        else:
            let_info = True
            
        ndiv = rows
        if sgcr > 0:
            ndiv -= 1
        ndiv = min(ndiv,rows-1)
        
        sg_eps = [0, sgcr, 1 - swc]
        ndiv = rows-1
        sgn = np.arange(0,1,1/ndiv)
        sg = sgn*(1-swc-sgcr)+sgcr
        sg = list(sg) + sg_eps
        sg = list(set(sg))
        sg.sort()
        sg = np.array(sg)
    
        # Assign gas relative permeabilities
        sgn = (sg - sgcr) / (1 - swc - sgcr)
        sgn = np.clip(sgn, 0, 1)
        if krfamily.name == 'COR':
            if not corey_info:
                print( 'Not enough information for SGWFN Corey Curves. Check if nw and ng are defined')
                return
            krg = krgmax * sgn ** ng
        if krfamily.name == 'LET':
            if not let_info:
                print( 'Not enough information for SGWFN LET Curves. Check if Lg, Eg, Tg, Lw, Ew & Tw are defined')
                return
            krg = krgmax*((sgn) ** Lg) / (1 + ((sgn) ** Lg) + (Eg * ((1 - sgn) ** Tg)) - 1)
            
        # Assign water relative permeabilities
        sgn = (sg) / (1 - swc)
        sgn = np.clip(sgn, 0, 1)
        if krfamily.name == 'COR':
            krw = krwmax * (1 - sgn) ** nw
        if krfamily.name == 'LET':
            krw = krwmax*((1 - sgn) ** Lw) / (1 + ((1 - sgn) ** Lw) + (Ew * (sgn ** Tw)) - 1)
        
        kr_df = pd.DataFrame()
        kr_df['Sg'] = sg
        kr_df['Krgw'] = krg
        kr_df['Krwg'] = krw
        return kr_df
    
    # Consistency checks
    fail = False
    if swcr < swc:
        swcr = swc
    if sorg+sgcr+swc >=1:
        print( 'sorg+sgcr+swc must be less than 1')
        fail = True
    if sorg+sgcr+swc >=1:
        print( 'sorg+sgcr+swc must be less than 1')
        fail = True   
    if sorw+swcr >=1:
        print( 'sorw+swcr must be less than 1')
        fail = True  
    if fail:
        print('Saturation consistency check failure: Check your inputs')
        sys.exit()

    if table_type.name == 'SWOF':
        return kr_SWOF(rows, table_type, krfamily, kromax, krgmax, krwmax, swc, swcr, sorg, sorw, sgcr, no, nw, ng, Lw, Ew, Tw, Lo, Eo, To, Lg, Eg, Tg)
    if table_type.name == 'SGOF':
        return kr_SGOF(rows, table_type, krfamily, kromax, krgmax, krwmax, swc, swcr, sorg, sorw, sgcr, no, nw, ng, Lw, Ew, Tw, Lo, Eo, To, Lg, Eg, Tg)
    if table_type.name == 'SGWFN':
        return kr_SGWFN(rows, table_type, krfamily, kromax, krgmax, krwmax, swc, swcr, sorg, sorw, sgcr, no, nw, ng, Lw, Ew, Tw, Lo, Eo, To, Lg, Eg, Tg)
    print( 'Check that you have specified table type as SWOF, SGOF or SGWFN')
    sys.exit() 