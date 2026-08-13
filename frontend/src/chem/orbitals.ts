export const orcaIndexToDisplayNumber = (orcaIndex: number) => {
  if (!Number.isInteger(orcaIndex) || orcaIndex < 0) throw new Error('ORCA orbital index는 0 이상의 정수여야 합니다')
  return orcaIndex + 1
}

export const displayNumberToOrcaIndex = (displayNumber: number) => {
  if (!Number.isInteger(displayNumber) || displayNumber < 1) throw new Error('표시 번호는 1 이상의 정수여야 합니다')
  return displayNumber - 1
}

