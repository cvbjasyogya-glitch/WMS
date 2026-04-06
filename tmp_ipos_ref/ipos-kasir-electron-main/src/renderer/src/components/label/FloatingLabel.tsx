import { FC } from 'react'

interface FloatingLabelProps {
  label: string
  shortcut?: string
}
const FloatingLabel: FC<FloatingLabelProps> = ({ ...props }) => {
  const { label, shortcut } = props

  return (
    <div className="absolute flex flex-col items-center w-[8em] py-2 left-full top-1 ml-2 text-white text-xs bg-[#282c34] border border-gray-300 rounded-md shadow-md">
      <div className="font-semibold text-xs">{label}</div>
      <div className="font-semibold text-gray-400">{shortcut}</div>
    </div>
  )
}

export { FloatingLabel }
