import { useEffect, useState } from 'react'

interface ToastProps {
  message: string
  type?: 'success' | 'error' | 'info'
  onClose: () => void
  duration?: number
}

export default function Toast({ message, type = 'info', onClose, duration = 3000 }: ToastProps) {
  const [isVisible, setIsVisible] = useState(true)

  useEffect(() => {
    const timer = setTimeout(() => {
      setIsVisible(false)
      setTimeout(onClose, 300) // wait for fade out
    }, duration)
    return () => clearTimeout(timer)
  }, [duration, onClose])

  if (!message) return null

  const bgColors = {
    success: 'bg-emerald-50 text-emerald-800 border-emerald-200',
    error: 'bg-red-50 text-red-800 border-red-200',
    info: 'bg-emerald-500\/10 text-blue-800 border-blue-200'
  }

  const iconMap = {
    success: '✅',
    error: '❌',
    info: 'ℹ️'
  }

  return (
    <div className="fixed bottom-4 right-4 z-50">
      <div
        className={`flex items-center gap-2 px-4 py-3 rounded-lg border shadow-lg transition-all duration-300 transform
          ${isVisible ? 'translate-y-0 opacity-100' : 'translate-y-2 opacity-0'}
          ${bgColors[type]}`}
      >
        <span>{iconMap[type]}</span>
        <span className="text-sm font-medium pr-4">{message}</span>
        <button
          onClick={() => {
            setIsVisible(false)
            setTimeout(onClose, 300)
          }}
          className="text-current opacity-50 hover:opacity-100 focus:outline-none"
        >
          ✕
        </button>
      </div>
    </div>
  )
}
