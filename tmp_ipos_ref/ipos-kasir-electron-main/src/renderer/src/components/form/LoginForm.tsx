import { useNavigate } from 'react-router-dom'
import { LuKeyRound, LuLogIn, LuMail } from 'react-icons/lu'
import { useState } from 'react'
import { InputText } from '../input/InputText'
import { Button } from '../button/Button'
import { Message } from '../message/Message'

interface PayloadData {
  email: string
  password: string
}

export function LoginForm() {
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  const formSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    const formData = new FormData(e.currentTarget)
    const payload: PayloadData = {
      email: (formData.get('email') as string) ?? '',
      password: (formData.get('password') as string) ?? ''
    }

    try {
      setLoading(true)
      setError('')

      const response = await (window.api as any).auth.login(payload)
      console.log(response)
      sessionStorage.setItem('user', JSON.stringify(response.data))
      if (response.success === true) navigate('/dashboard')

      setLoading(false)
      if (!response.success) setError(response.error || 'Unknown error')
    } catch (error) {
      setLoading(false)
      setError(error as string)
    }
  }

  return (
    <>
      <form onSubmit={formSubmit} action="" className="flex flex-col gap-y-6 w-[30em] ">
        {error && <Message text={error} variant="danger" onClick={() => setError('')} />}
        <InputText
          icon={<LuMail size={20} />}
          type="text"
          placeholder="masukkan email"
          name="email"
          label="Email"
        />
        <InputText
          icon={<LuKeyRound size={20} />}
          type="password"
          placeholder="masukkan password"
          name="password"
          label="Password"
        />
        <Button label="Masuk" disabled={loading} icon={<LuLogIn size={20} />} />
      </form>
    </>
  )
}
