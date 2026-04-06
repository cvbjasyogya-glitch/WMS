import logo from '../../assets/stack.svg'
import { LoginForm } from '../../components/form/LoginForm'
import { WindowLayout } from '../../layout/WindowLayout'

export function LoginPage() {
  return (
    <>
      <WindowLayout>
        <div className="bg-slate-50 flex flex-col h-screen justify-center items-center">
          <div className="mb-12">
            <div className="flex flex-col text-center justify-center gap-y-2 mb-8">
              <img className="w-auto h-[4vh]" src={logo} alt="" />
              <h1 className="font-bold text-2xl text-gray-500">iPos Sales Kasir</h1>
            </div>
            <h1 className="text-md font-semibold py-6 text-gray-500">
              Selamat datang, silahkan login
            </h1>
            <LoginForm />
            <div className="flex items-center pt-8 gap-x-2">
              <p className="text-sm  text-gray-400 ">iPos v1.0.0</p>
            </div>
          </div>
        </div>
      </WindowLayout>
    </>
  )
}
