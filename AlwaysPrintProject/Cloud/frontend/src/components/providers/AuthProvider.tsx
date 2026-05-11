'use client'

import { createContext, useContext, useState, useEffect, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { authApi, usersApi } from '@/lib/api'
import type { User, LoginRequest, UserRole } from '@/types'

interface AuthState {
  user: User | null
  isAuthenticated: boolean
  isLoading: boolean
  error: string | null
}

interface AuthContextValue extends AuthState {
  login: (credentials: LoginRequest) => Promise<void>
  logout: () => Promise<void>
  hasRole: (role: UserRole) => boolean
  isAdmin: () => boolean
  isOperator: () => boolean
  refreshUser: () => Promise<void>
  updateLanguage: (language: 'en' | 'es') => Promise<void>
  getAuthHeaders: () => { Authorization: string; 'Content-Type': string }
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const [state, setState] = useState<AuthState>({
    user: null,
    isAuthenticated: false,
    isLoading: true,
    error: null,
  })

  useEffect(() => {
    const token = localStorage.getItem('access_token')
    const userStr = localStorage.getItem('user')
    if (token && userStr) {
      try {
        const user = JSON.parse(userStr)
        setState({ user, isAuthenticated: true, isLoading: false, error: null })
      } catch {
        localStorage.removeItem('access_token')
        localStorage.removeItem('user')
        setState({ user: null, isAuthenticated: false, isLoading: false, error: null })
      }
    } else {
      setState({ user: null, isAuthenticated: false, isLoading: false, error: null })
    }
  }, [])

  const login = useCallback(async (credentials: LoginRequest) => {
    setState((prev) => ({ ...prev, isLoading: true, error: null }))
    try {
      const tokenResponse = await authApi.login(credentials)
      localStorage.setItem('access_token', tokenResponse.access_token)
      const user = await authApi.me()
      localStorage.setItem('user', JSON.stringify(user))
      setState({ user, isAuthenticated: true, isLoading: false, error: null })
      router.push('/dashboard')
    } catch (error: any) {
      let errorMessage = 'Error al iniciar sesión'
      if (error?.detail) errorMessage = error.detail
      else if (error?.message) errorMessage = error.message
      else if (typeof error === 'string') errorMessage = error
      setState({ user: null, isAuthenticated: false, isLoading: false, error: errorMessage })
      throw error
    }
  }, [router])

  const logout = useCallback(async () => {
    try { await authApi.logout() } catch { /* ignore */ }
    localStorage.removeItem('access_token')
    localStorage.removeItem('user')
    setState({ user: null, isAuthenticated: false, isLoading: false, error: null })
    router.push('/login')
  }, [router])

  const hasRole = useCallback((role: UserRole): boolean => state.user?.role === role, [state.user])
  const isAdmin = useCallback((): boolean => state.user?.role === 'admin', [state.user])
  const isOperator = useCallback((): boolean => state.user?.role === 'operator', [state.user])

  const refreshUser = useCallback(async () => {
    try {
      const user = await authApi.me()
      localStorage.setItem('user', JSON.stringify(user))
      setState((prev) => ({ ...prev, user }))
    } catch (error) {
      console.error('Error al refrescar usuario:', error)
    }
  }, [])

  const updateLanguage = useCallback(async (language: 'en' | 'es') => {
    try {
      await usersApi.updateLanguage(language)
      setState((prev) => {
        if (!prev.user) return prev
        const updatedUser = { ...prev.user, language }
        localStorage.setItem('user', JSON.stringify(updatedUser))
        return { ...prev, user: updatedUser }
      })
    } catch (error) {
      console.error('Error al actualizar idioma:', error)
    }
  }, [])

  const getAuthHeaders = useCallback(() => {
    const token = localStorage.getItem('access_token')
    return { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }
  }, [])

  return (
    <AuthContext.Provider value={{
      ...state,
      login, logout, hasRole, isAdmin, isOperator,
      refreshUser, updateLanguage, getAuthHeaders,
    }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
