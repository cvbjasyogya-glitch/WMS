import { cva } from 'class-variance-authority'
import { ReactNode, useState, forwardRef } from 'react'
import { LuEye, LuEyeClosed } from 'react-icons/lu'
import { cn } from '../../utils/utils'

interface InputProps {
  placeholder: string
  onChange?: (e: React.ChangeEvent<HTMLInputElement>) => void
  name: string
  label: string
  type: string
  icon?: ReactNode
  style?: React.CSSProperties
  variant?: 'default' | 'danger' | 'secondary'
  outline?: 'box' | 'underline' | 'none'
  className?: string
  iconBgColor?: string
  onKeyDown?: (e: React.KeyboardEvent<HTMLInputElement>) => void;
  required?: boolean
  value?: string
}

const Variants = cva('p-4 flex gap-x-4 items-center duration-200 transition-all', {
  variants: {
    variant: {
      default: 'focus-within:border-blue-500',
      danger: 'focus-within:border-red-500',
      secondary: 'focus-within:border-gray-500'
    },
    outline: {
      none: 'border-none',
      box: 'border',
      underline: 'border-b'
    }
  },
  defaultVariants: {
    variant: 'default',
    outline: 'underline'
  }
})

const InputText = forwardRef<HTMLInputElement, InputProps>((props, ref) => {
  const {
    icon: Icon,
    type,
    placeholder,
    name,
    label,
    style,
    variant,
    outline,
    className,
    iconBgColor,
    required,
    value
  } = props
  const [isPasswordVisible, setIsPasswordVisible] = useState(false)

  return (
    <div className={cn(Variants({ variant, outline }), className)}>
      <div className="flex items-center gap-x-4 w-full">
        <div className={cn(iconBgColor)}>
          <label className="" htmlFor={label}>
            {Icon && Icon}
          </label>
        </div>
        <input
          ref={ref}
          type={type === 'password' ? (isPasswordVisible ? 'text' : 'password') : type}
          placeholder={placeholder}
          name={name}
          step={type === 'number' ? 'any' : undefined}
          id={label}
          className="bg-transparent border-none outline-none w-full"
          style={style}
          required={required}
          onChange={props.onChange}
          onKeyDown={props.onKeyDown}
          value={value}
        />
      </div>
      {type === 'password' && (
        <div className="flex justify-end items-center">
          <button type="button" onClick={() => setIsPasswordVisible(!isPasswordVisible)}>
            {isPasswordVisible ? <LuEye size={20} /> : <LuEyeClosed size={20} />}
          </button>
        </div>
      )}
    </div>
  )
})

export { InputText }
