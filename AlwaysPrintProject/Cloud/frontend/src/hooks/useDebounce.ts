'use client'

import { useState, useEffect } from 'react'

/**
 * Hook que retorna un valor con debounce.
 * El valor solo se actualiza después de que pase el delay sin cambios.
 */
export function useDebounce<T>(value: T, delay: number = 400): T {
  const [debouncedValue, setDebouncedValue] = useState<T>(value)

  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedValue(value)
    }, delay)

    return () => {
      clearTimeout(timer)
    }
  }, [value, delay])

  return debouncedValue
}
