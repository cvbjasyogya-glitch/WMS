import { MasterNav } from '../components/navigation/MasterNav'

interface MasterLayoutProps {
  children: React.ReactNode
  title: string
  desc: string
}

export function MasterLayout({ children, title, desc }: MasterLayoutProps) {
  return (
    <div className="py-6 px-4">
      <div className="bg-white border p-4">
        <MasterNav />
        <div className="mt-[-2px] border p-2">
          <div className="p-4 flex flex-col gap-y-4">
            <div className="">
              <div className="font-semibold text-lg mb-2">{title}</div>{' '}
              <div className="text-gray-600">{desc}</div>
            </div>
            <div className="">{children}</div>
          </div>
        </div>
      </div>
    </div>
  )
}
