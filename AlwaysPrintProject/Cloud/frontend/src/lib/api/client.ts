/**
 * Cliente API configurado con axios.
 */

import axios from 'axios';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'https://alwaysprint.apps.iol.pe';

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
  withCredentials: true,
});

// Interceptor para agregar token de autenticación
apiClient.interceptors.request.use(
  (config) => {
    // Aquí se puede agregar el token de autenticación si es necesario
    // const token = getAuthToken();
    // if (token) {
    //   config.headers.Authorization = `Bearer ${token}`;
    // }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// Interceptor para manejar errores de respuesta.
//
// Normaliza el error al contrato `{ status, detail }` que consumen los handlers de la app
// (p. ej. recycle-policy, que lee `error.status` y `error.detail` para distinguir 422 vs 409).
// Axios expone el código HTTP en `error.response.status` y el cuerpo en `error.response.data`;
// aquí se copian a nivel raíz SIN eliminar las props originales de axios, para no romper a los
// callers que aún leen `error.response`.
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // Manejar error de autenticación
      // Por ejemplo, redirigir al login
    }

    if (error?.response) {
      // `detail` es el cuerpo estándar de error de FastAPI: puede ser un string (409/500),
      // un objeto (`{errors: [...]}` en los 422 de recycle-policy) o un array (422 de Pydantic).
      const data = error.response.data;
      error.status = error.response.status;
      error.detail =
        data && typeof data === 'object' && 'detail' in data
          ? (data as { detail: unknown }).detail
          : data;
    }

    return Promise.reject(error);
  }
);
