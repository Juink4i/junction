import { describe, expect, it } from 'vitest'
import { allergenName, eur, shortHash, tagName, unitsBothWays } from './format'

describe('format', () => {
  it('states units both ways', () => {
    expect(unitsBothWays({ units: 1000, sales_unit: 'ST', covers: 1000, content_unit: 'L' })).toBe('1,000 × pc (1,000 L)')
    expect(unitsBothWays({ units: 50, sales_unit: 'KI', covers: 1000, content_unit: 'L' })).toBe('50 × case (1,000 L)')
  })

  it('formats euros', () => {
    expect(eur(1010)).toBe('€1,010.00')
    expect(eur(null)).toBe('—')
  })

  it('shortens hashes', () => {
    expect(shortHash('a3f9000000c21e')).toBe('a3f9…c21e')
  })

  it('names tags and allergens', () => {
    expect(tagName('FREE_FROM_LACTOSE')).toBe('Lactose-free')
    expect(allergenName('AP')).toBe('Peanuts')
    expect(allergenName('ZZ')).toBe('ZZ')
  })
})
