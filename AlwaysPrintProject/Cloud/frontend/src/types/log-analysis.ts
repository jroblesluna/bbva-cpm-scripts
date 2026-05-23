/**
 * Tipos relacionados con el análisis de logs de workstations.
 */

export interface LogAnalysisResponse {
  id: string
  workstation_id: string
  organization_id: string
  analysis_date: string
  analysis_text: string
  processing_path: 'direct' | 'structural'
  log_size_bytes: number
  processing_duration_ms: number
  original_filename: string
  created_at: string
  updated_at: string
}

export interface LogAnalysisTodayCheckResponse {
  exists: boolean
  analysis_id: string | null
  analysis_date: string | null
}

export interface LogAnalysisListResponse {
  items: LogAnalysisResponse[]
  total: number
  page: number
  page_size: number
}
