P_mp = I_mp * V_mp

V_th,0 = T_m,0 * k[J/K]/q[C]

Tm = 273.15 + T_a + G * (NOCT-20)/800

if G = 1000; Ta = 2, if G = 800, Ta = 10
if 600, Ta = 15
if 400, Ta = 18
if 200, Ta = 23


[iteration]; 
n_G = (V_oc,0 - V_mp,0-V_th,0*N_S)/(V_th,0*N_S*ln(I_sc,0/(I_sc,0-I_mp,0)))

n_S = (V_oc,0-V_mp,0)/(V_th,0*N_S*ln(V_mp,0/(V_th,0*N_S)))

n_p = (I_sc,0 - I_mp,0)*(V_mp,0-V_th,0*N_S)/(I_sc,0*V_th,0*N_S)

n = min(n_G, n_S, n_p)

R_S = (V_oc,0 - V_mp,0 - n * V_th,0*N_S*ln(V_mp,0/(n*V_th,0*N_S)))/I_mp,0


R_SH = ((V_mp,0 - I_MP,0*R_S)*V_mp,0 - n * V_th,0*N_S*V_mp,0)/((V_mp,0-I_mp,0*R_S)(I_sc,0-I_mp,0)-n*V_th,0*N_S*I_mp,0)-R_S 

alpha(i) = (V_mp,0+n*V_th,0*N_S-I_mp,0*R_S_before)/(n*V_th,0*N_S)

beta(i) = (I_sc,0*(R_s+R_sh)-V_oc,0)/(I_sc,0*(R_s+R_sh)-2*V_mp,0)

next_n_G = (V_oc,0 - V_mp,0 -I_mp,0*R_s)/(V_th,0*N_S*ln((I_sc,0*(R_s+R_sh)-V_oc,0)/((I_sc,0-I_mp,0)*(R_s+R_sh)-V_mp,0)))

next_eta = abs(n - next_n)

next_R_S = (V_oc,0 - V_mp,0 - 
n * V_th,0*N_S*ln(alpha(i)*beta(i)))/I_mp,0

next_R_sh = ((V_mp,0 - I_MP,0*R_S)*V_mp,0 - 
n * V_th,0*N_S*V_mp,0)/((V_mp,0-I_mp,0*R_S)(I_sc,0-I_mp,0)-n*V_th,0*N_S*I_mp,0)-R_S 







etc...
iterate until convergence to obtain n_0, R_s,0, R_sh,0
[/iteration]

T_m,0 = 25 C
G_stc = 1000 W/m2

V_oc = V_oc,0 * (1+beta_voc/100*(T_m-T_m,0))+N_S*n*V_th*ln(G/G_stc)

I_sc = I_sc,0 * (1+alpha_sc/100*(T_m-T_m,0))

V_th = k / q * (T_m+273.15)

n = n * (T_m0+273.15)/(T_m+273.15) 

R_sh = R_sh,0 * G_stc/G

R_s = R_s,0 * (T_m+273.15)/(T_m,0+273.15)*(1-0.217*ln(G/G_stc))

I_L = I_sc * (R_s+R_sh)/R_s

I_0 = ((R_sh+R_s)*I_sc-V_oc)*exp(-V_oc/(n*N_S*V_th))/R_sh

V = n*N_S*V_th*ln((I_L-I-(V_mp+I*R_s)/R_sh+I_0)/I_0) - I*R_s

a = -(R_s+R_sh)*R_s/(n*N_S*V_th)

b = (R_s+R_sh)*(1+V_m/(n*N_S*V_sth))+R_s/(n*N_S*V_th)*((I_L+I_0)*R_sh-V_m)

c = 2*I_0*R_sh-V_m*((I_L+I_0)*R_sh/(n*N_S*V_th)+1)+V_m**2/(n*N_S*V_th)

I = (-b+sqrt(b**2-4*a*c))/(2*a)

P = V*I 




