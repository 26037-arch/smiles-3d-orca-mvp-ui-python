export interface ElementStyle { atomicNumber: number; radius: number; color: string }

const symbols = 'H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr'.split(' ')
const covalent: Record<string, number> = {
  H: .31, He: .28, Li: 1.28, Be: .96, B: .84, C: .76, N: .71, O: .66, F: .57, Ne: .58,
  Na: 1.66, Mg: 1.41, Al: 1.21, Si: 1.11, P: 1.07, S: 1.05, Cl: 1.02, Ar: 1.06,
  K: 2.03, Ca: 1.76, Fe: 1.32, Co: 1.26, Ni: 1.24, Cu: 1.32, Zn: 1.22,
  Br: 1.20, I: 1.39,
}
const colors: Record<string, string> = {
  H: '#f4f7ff', C: '#25364a', N: '#4067ff', O: '#ff4057', F: '#55db78', P: '#ff9b43',
  S: '#ffe34f', Cl: '#45d66b', Br: '#a75438', I: '#8456be', Fe: '#e17932', default: '#8da0b9',
}

export const ELEMENTS: Record<string, ElementStyle> = Object.fromEntries(
  symbols.map((symbol, i) => [symbol, { atomicNumber: i + 1, radius: covalent[symbol] ?? 1.35, color: colors[symbol] ?? colors.default }]),
)

export function normalizeElement(value: string): string | null {
  const normalized = value.slice(0, 1).toUpperCase() + value.slice(1).toLowerCase()
  return ELEMENTS[normalized] ? normalized : null
}

