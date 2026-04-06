import { FC } from 'react'
import { IconType } from 'react-icons'
import { useDispatch } from 'react-redux'
import { useLocation, useNavigate } from 'react-router-dom'
import { setTabIdx } from '../../../reducers/tabReducer'

interface Props {
  Icon: IconType
  label: string
  path: string
  index: number
}

const MasterButton: FC<Props> = ({ Icon, label, path, index }) => {
  const dispatch = useDispatch()
  const location = useLocation()
  const isActive = location.pathname === path
  const navigate = useNavigate()

  const handleClick = () => {
    dispatch(setTabIdx(index))
    navigate(path)
  }

  return (
    <div onClick={handleClick} className="cursor-pointer">
      <div
        className={`flex items-center gap-x-2 text-gray-400 p-4 hover:text-blue-500 group ${isActive ? 'bg-white border-t-4 border-x border-t-blue-500' : ''}`}
      >
        <Icon
          size={20}
          className={`transition-colors duration-200 ${isActive ? 'text-blue-500' : 'text-gray-400'} group-hover:text-blue-500`}
        />
        <div
          className={`transition-colors duration-200 ${isActive ? 'text-blue-500' : 'text-gray-400'} group-hover:text-blue-500`}
        >
          {label}
        </div>
      </div>
    </div>
  )
}

export { MasterButton }
