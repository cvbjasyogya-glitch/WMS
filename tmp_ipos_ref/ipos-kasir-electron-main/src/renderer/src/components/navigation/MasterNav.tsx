import { IconType } from 'react-icons'
import { FaBoxes, FaClipboardList, FaCube, FaDollarSign, FaTags } from 'react-icons/fa'
import { MasterButton } from '../button/variants/MasterButton'
import { useEffect } from 'react'
import { useSelector, useDispatch } from 'react-redux'
import { setTabIdx } from '../../reducers/tabReducer'
import { useNavigate } from 'react-router-dom'
import { TiWarning } from "react-icons/ti";
// import { BiSolidDiscount } from "react-icons/bi";

interface Path {
  icon: IconType
  label: string
  path: string
}

const MasterNav: React.FC = () => {
  const dispatch = useDispatch()
  const navigate = useNavigate()
  const prefix = 'master'
  const tabIdx = useSelector((state: any) => state.tab.tabIdx)
  const paths: Path[] = [
    { icon: FaClipboardList, label: 'Products ', path: `/${prefix}` },
    { icon: FaBoxes, label: 'Stock ', path: `/${prefix}/stock` },
    { icon: FaCube, label: 'Satuan ', path: `/${prefix}/unit` },
    { icon: FaTags, label: 'Kategory ', path: `/${prefix}/category` },
    { icon: FaDollarSign, label: 'Harga jual ', path: `/${prefix}/price` },
    // { icon: BiSolidDiscount, label: 'Discount ', path: `/${prefix}/discount` }
  ]

  const handleKeyDown = (event: KeyboardEvent) => {
    if (event.altKey && event.key === 'ArrowRight') {
      event.preventDefault()
      const nextIdx = (tabIdx + 1) % paths.length
      dispatch(setTabIdx(nextIdx))
      navigate(paths[nextIdx].path)
    }
    if (event.altKey && event.key === 'ArrowLeft') {
      event.preventDefault()
      const prevIdx = (tabIdx - 1 + paths.length) % paths.length
      dispatch(setTabIdx(prevIdx))
      navigate(paths[prevIdx].path)
    }
  }

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown)
    return () => {
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [tabIdx, dispatch])

  return (
    <div>
      <div className="bg-yellow-50 rounded mb-4 p-4 w-1/5 border border-yellow-500">
        <div className="flex items-center gap-x-1 text-yellow-600">
          <TiWarning size={20} />
          <div className="  font-bold text-base">Tips Shortcut</div>
        </div>
        <div className=" text-yellow-600 text-sm">alt + arrow untuk pindah tab</div>
      </div>
      <div className="flex gap-x-4">
        {paths.map((item, index) => (
          <div key={index} className="flex items-center gap-x-2">
            <MasterButton index={index} Icon={item.icon} label={item.label} path={item.path} />
          </div>
        ))}
      </div>
    </div>
  )
}

export { MasterNav }
