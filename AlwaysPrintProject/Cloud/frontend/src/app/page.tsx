import { redirect } from 'next/navigation'

export default function Home() {
  // Redirigir a dashboard
  redirect('/dashboard')
}
