/**
 * Selector de locale para configuración de workstations.
 *
 * Permite seleccionar el idioma que usarán los mensajes del Tray Client:
 * - "" (vacío): Automático, usa el idioma del sistema operativo
 * - "es": Español
 * - "en": English
 */

'use client'

interface LocaleSelectorProps {
  /** Valor actual del locale ("", "es", "en") */
  value: string
  /** Callback cuando el usuario selecciona un valor diferente */
  onChange: (value: string) => void
}

/** Opciones disponibles para el selector de locale */
const LOCALE_OPTIONS: { value: string; label: string }[] = [
  { value: '', label: 'Automático (Sistema)' },
  { value: 'es', label: 'Español' },
  { value: 'en', label: 'English' },
]

export function LocaleSelector({ value, onChange }: LocaleSelectorProps) {
  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-2">
        Locale
      </label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full max-w-md px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
      >
        {LOCALE_OPTIONS.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      <p className="mt-1 text-sm text-gray-500">
        Idioma para los mensajes del Tray en las workstations. Seleccione
        &quot;Automático&quot; para usar el idioma del sistema operativo.
      </p>
    </div>
  )
}
