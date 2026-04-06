import { FC, useEffect, useState } from 'react'
import logo from '../../assets/stack.svg'
import { BarItem } from './baritem/BarItem'
import { UserData } from '../../utils/props'
import { FaSignOutAlt } from 'react-icons/fa'

const Header: FC<any> = () => {
  const [currentTime, setCurrentTime] = useState(new Date())
  const [userData, setUserData] = useState<UserData>({ id: '', name: '', email: '', role_id: 0 })
  const [showModal, setShowModal] = useState(false)

  useEffect(() => {
    const data = JSON.parse(sessionStorage.getItem('user') || '{}')
    setUserData(data)

    const intervalId = setInterval(() => {
      setCurrentTime(new Date())
    }, 1000)
    return () => clearInterval(intervalId)
  }, [])

  return (
    <header className="fixed w-full border-b-[6px] border-b-blue-500 bg-[#282c34] z-10 text-white py-2 px-8">
      <div className="py-2 flex items-center justify-between">
        <div className="flex gap-x-4 items-center">
          <img src={logo} alt="Logo" className="w-auto h-7" />
          <h1 className="font-medium text-xl">iPos Sales</h1>
        </div>
        <div className="flex gap-x-4">
          <BarItem label="Tanggal" text={currentTime.toDateString()} />
          <BarItem label="Waktu" text={currentTime.toLocaleTimeString()} />
          <BarItem label="Kasir" text={userData.name} />
          <div className="flex flex-col justify-end pl-8 text-xl">
            <div className="flex items-center gap-x-2">
              <button onClick={() => setShowModal(true)}>Keluar</button>
              <FaSignOutAlt />
            </div>
          </div>
        </div>
      </div>

      {showModal && (
        <div className="fixed inset-0 flex items-center justify-center bg-black bg-opacity-50">
          <div className="bg-white p-6 rounded-lg shadow-lg text-center">
            <h2 className="text-lg text-black font-semibold mb-4">Akhiri sesi?</h2>
            <div className="flex justify-center gap-x-4">
              <button onClick={() => { window.electron.ipcRenderer.send('close-me') }}
                className="bg-red-500 text-white px-4 py-2 rounded-lg hover:bg-red-600"
              >
                Ya, Akhiri
              </button>
              <button
                onClick={() => setShowModal(false)}
                className="bg-gray-200 text-gray-700 px-4 py-2 rounded-lg hover:bg-gray-300"
              >
                Batal
              </button>
            </div>
          </div>
        </div>
      )}
    </header>
  )
}

export { Header }
