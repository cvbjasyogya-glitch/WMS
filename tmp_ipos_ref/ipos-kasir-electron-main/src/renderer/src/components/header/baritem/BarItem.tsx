import { FC } from 'react'

interface ItemProps {
  label: string
  text: string
}
const BarItem: FC<ItemProps> = ({ ...props }) => {
  const { label, text } = props
  return (
    <div className="">
      <div className="border-r px-8">
        <div className="text-end text-sm mb-1">{label}</div>
        <div className="font-bold text-end text-lg">{text}</div>
      </div>
    </div>
  )
}

export { BarItem }
