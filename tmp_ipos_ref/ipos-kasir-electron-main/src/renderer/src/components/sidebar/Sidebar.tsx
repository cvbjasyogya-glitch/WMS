import { FC, useEffect, useState } from 'react'
import { IconType } from 'react-icons'
import { TiThLarge } from 'react-icons/ti'
import { FaDatabase, FaReceipt, FaUsers } from 'react-icons/fa'
import { IconButton } from '../button/IconButton'
import { ImBoxAdd, ImBoxRemove } from "react-icons/im";

interface Path {
  icon: IconType
  label: string
  path: string
}

const Sidebar: FC<any> = () => {
  const [filteredPaths, setFilteredPaths] = useState<Path[]>([])

  const paths: Path[] = [
    { icon: TiThLarge, label: 'Dashboard', path: '/dashboard' },
    { icon: FaDatabase, label: 'Master', path: '/master' },
    { icon: FaUsers, label: 'Pembeli', path: '/point' },
    { icon: ImBoxAdd, label: 'Barang Masuk', path: '/inbound' },
    { icon: ImBoxRemove, label: 'Barang Keluar', path: '/outbound' },
    { icon: FaReceipt, label: 'Invoice', path: '/transaction' }
  ]

  useEffect(() => {
    const data = JSON.parse(sessionStorage.getItem('user') || '{}')
    const filter = data.role_id === 3 ? paths.filter((path) => path.path !== '/master') : paths
    setFilteredPaths(filter)
  }, [])

  return (
    <div className="fixed h-screen bg-white px-2 flex flex-col items-center justify-center shadow border z-[1]">
      <div className="flex flex-col gap-y-3 mb-12">
        {filteredPaths.map((item, index) => (
          <IconButton
            key={item.path}
            Icon={item.icon}
            label={item.label}
            path={item.path}
            shortcut={(index + 1).toString()}
          />
        ))}
      </div>
    </div>
  )
}

export { Sidebar }
