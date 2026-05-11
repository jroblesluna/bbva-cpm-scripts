/**
 * Hook de autenticación.
 * 
 * Proporciona:
 * - Estado de autenticación
 * - Usuario actual
 * - Funciones de login/logout
 * - Verificación de permisos
 */

'use client'

import { useState, useEffect, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { authApi, usersApi } from '@/lib/api'
import type { User, LoginRequest, UserRole } from '@/types'

interface AuthState {
  user: User | null
  isAuthenticated: boolean
  isLoading: boolean
  error: string | null
}

export function useAuth() {
  const router = useRouter()
  const [state, setState] = useState<AuthState>({
    user: null,
    isAuthenticated: false,
    isLoading: true,
    error: null,
  })

  /**
   * Cargar usuario desde localStorage al montar.
   */
  useEffect(() => {
    const loadUser = async () => {
      const token = localStorage.getItem('access_token')
      const userStr = localStorage.getItem('user')

      if (token && userStr) {
        try {
          const user = JSON.parse(userStr)
          setState({
            user,
            isAuthenticated: true,
            isLoading: false,
            error: null,
          })
        } catch (error) {
          // Si hay error al parsear, limpiar localStorage
          localStorage.removeItem('access_token')
          localStorage.removeItem('user')
          setState({
            user: null,
            isAuthenticated: false,
            isLoading: false,
            error: null,
          })
        }
      } else {
        setState({
          user: null,
          isAuthenticated: false,
          isLoading: false,
          error: null,
        })
      }
    }

    loadUser()
  }, [])

  /**
   * Login de usuario.
   */
  const login = useCallback(
    async (credentials: LoginRequest) => {
      setState((prev) => ({ ...prev, isLoading: true, error: null }))

      try {
        // Hacer login
        const tokenResponse = await authApi.login(credentials)

        // Guardar token
        localStorage.setItem('access_token', tokenResponse.access_token)

        // Obtener datos del usuario
        const user = await authApi.me()

        // Guardar usuario
        localStorage.setItem('user', JSON.stringify(user))

        setState({
          user,
          isAuthenticated: true,
          isLoading: false,
          error: null,
        })

        // Redirigir a dashboard
        router.push('/dashboard')
      } catch (error: any) {
        // Mejorar manejo de errores
        let errorMessage = 'Error al iniciar sesión'
        
        if (error?.detail) {
          errorMessage = error.detail
        } else if (error?.message) {
          errorMessage = error.message
        } else if (typeof error === 'string') {
          errorMessage = error
        }
        
        // Solo loggear en desarrollo si no es un error de autenticación esperado
        if (process.env.NODE_ENV === 'development' && error?.status !== 401) {
          console.error('Error inesperado en login:', error)
        }
        
        setState({
          user: null,
          isAuthenticated: false,
          isLoading: false,
          error: errorMessage,
        })
        throw error
      }
    },
    [router]
  )

  /**
   * Logout de usuario.
   */
  const logout = useCallback(async () => {
    try {
      await authApi.logout()
    } catch (error) {
      // Ignorar errores de logout
      console.error('Error al hacer logout:', error)
    } finally {
      // Limpiar localStorage
      localStorage.removeItem('access_token')
      localStorage.removeItem('user')

      setState({
        user: null,
        isAuthenticated: false,
        isLoading: false,
        error: null,
      })

      // Redirigir a login
      router.push('/login')
    }
  }, [router])

  /**
   * Verificar si el usuario tiene un rol específico.
   */
  const hasRole = useCallback(
    (role: UserRole): boolean => {
      return state.user?.role === role
    },
    [state.user]
  )

  /**
   * Verificar si el usuario es admin.
   */
  const isAdmin = useCallback((): boolean => {
    return state.user?.role === 'admin'
  }, [state.user])

  /**
   * Verificar si el usuario es operador.
   */
  const isOperator = useCallback((): boolean => {
    return state.user?.role === 'operator'
  }, [state.user])

  /**
   * Refrescar datos del usuario.
   */
  const refreshUser = useCallback(async () => {
    try {
      const user = await authApi.me()
      localStorage.setItem('user', JSON.stringify(user))
      setState((prev) => ({ ...prev, user }))
    } catch (error) {
      console.error('Error al refrescar usuario:', error)
    }
  }, [])

  /**
   * Actualizar idioma del usuario autenticado.
   */
  const updateLanguage = useCallback(async (language: 'en' | 'es') => {
    try {
      await usersApi.updateLanguage(language)
      const updatedUser = state.user ? { ...state.user, language } : null
      if (updatedUser) {
        localStorage.setItem('user', JSON.stringify(updatedUser))
        setState((prev) => ({ ...prev, user: updatedUser }))
      }
    } catch (error) {
      console.error('Error al actualizar idioma:', error)
    }
  }, [state.user])

  /**
   * Obtener headers de autenticación para requests.
   */
  const getAuthHeaders = useCallback(() => {
    const token = localStorage.getItem('access_token')
    return {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json',
    }
  }, [])

  return {
    user: state.user,
    isAuthenticated: state.isAuthenticated,
    isLoading: state.isLoading,
    error: state.error,
    login,
    logout,
    hasRole,
    isAdmin,
    isOperator,
    refreshUser,
    getAuthHeaders,
    updateLanguage,
  }
}
