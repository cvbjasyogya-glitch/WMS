import React from 'react'
import { Sidebar } from '../components/sidebar/Sidebar'
import { Header } from '../components/header/Header'
import { WindowLayout } from './WindowLayout'

interface LayoutProps {
  children: React.ReactNode
}

const MainLayout: React.FC<LayoutProps> = ({ children }) => {
  return (
    <div>
      <WindowLayout>
        <Header />
        <main>
          <div className="flex">
            <Sidebar />
            <div className="w-full pt-[8vh] pl-[4.65em]">{children}</div>
          </div>
        </main>
      </WindowLayout>
    </div>
  )
}

export default MainLayout
