import { describe, expect, it } from 'vitest'
import { findCategories } from './answers'

const items = [
  { code: '10400', name: 'Milk and sour milk', examples: ['Valio skimmed milk 1 l'] },
  { code: '10402', name: 'Plant-based drinks', examples: ['Oatly Oat Drink Semi 1L', 'Alpro Rice drink 1L'] },
  { code: '10500', name: 'Butter', examples: ['Valio butter 500 g salted'] },
  { code: '10515', name: 'Butter spreads', examples: ['Flora Professional 75% 2kg'] },
  { code: '22413', name: 'Ice cream', examples: ['Suomen Jäätelö Milk ice cream 5l'] },
]

describe('findCategories', () => {
  it('finds a category by an example product when its name does not match', () => {
    expect(findCategories(items, 'oat', []).map((c) => c.code)).toEqual(['10402'])
  })

  it('matches from the start of a word, not inside one', () => {
    const goat = [...items, { code: '10620', name: 'Goat and sheep cheeses', examples: ['Soignon goat cheese 180g'] }]
    expect(findCategories(goat, 'oat', []).map((c) => c.code)).toEqual(['10402'])
    expect(findCategories(goat, 'oat drink', []).map((c) => c.code)).toEqual(['10402'])
  })

  it('lists name matches before example matches', () => {
    expect(findCategories(items, 'milk', []).map((c) => c.code)).toEqual(['10400', '22413'])
  })

  it('matches a code and ignores case', () => {
    expect(findCategories(items, '10515', []).map((c) => c.code)).toEqual(['10515'])
    expect(findCategories(items, 'BUTTER', []).map((c) => c.code)).toEqual(['10500', '10515'])
  })

  it('leaves out what is already picked, and finds nothing for an empty query', () => {
    expect(findCategories(items, 'butter', ['10500']).map((c) => c.code)).toEqual(['10515'])
    expect(findCategories(items, '  ', [])).toEqual([])
  })
})
