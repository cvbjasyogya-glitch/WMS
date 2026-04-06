import React, { useEffect, useState } from 'react'
import { IconType } from 'react-icons'
import { useLocation, useNavigate } from 'react-router-dom'
import { FloatingLabel } from '../label/FloatingLabel'

interface Props {
  Icon: IconType
  label: string
  path: string
  shortcut: string
}

const IconButton: React.FC<Props> = ({ ...props }) => {
  const { Icon, label, path, shortcut } = props
  const location = useLocation()
  const navigate = useNavigate()
  const [isHovered, setIsHovered] = useState(false)
  const isActive = location.pathname.includes(path)

  const handleKeyDown = (event: KeyboardEvent) => {
    if (event.ctrlKey && event.key === shortcut) {
      event.preventDefault()
      navigate(path)
    }
  }

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown)
    return () => {
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [])

  return (
    <div onClick={() => navigate(path)}>
      <div
        className={`p-4 rounded-md cursor-pointer duration-200 transition-all group relative 
            ${isActive ? 'bg-blue-100' : ''} hover:bg-blue-100`}
        onMouseEnter={() => setIsHovered(true)}
        onMouseLeave={() => setIsHovered(false)}
      >
        <div className={`flex items-center justify-center`}>
          <Icon
            className={`transition-colors duration-200 ${isActive ? 'text-blue-500' : 'text-gray-400'} group-hover:text-blue-500`}
            size={24}
          />
        </div>
        {isHovered && <FloatingLabel label={label} shortcut={`ctrl + ${shortcut}`} />}
      </div>
    </div>
  )
}

export { IconButton }
