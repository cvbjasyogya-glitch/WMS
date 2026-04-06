import { IconType } from "react-icons"
import { forwardRef } from 'react'

interface Props {
    Icon: IconType
    value: string | number
    onChange?: (e: React.ChangeEvent<HTMLSelectElement>) => void
    datas: any
    name: string
    placeholder: string
}

export const InputSelect = forwardRef<HTMLSelectElement, Props>((props, ref) => {
    const { Icon, value, onChange, datas, name, placeholder } = props
    return (
        <>
            <div className="flex items-center gap-x-4 border w-fit bg-white border-blue-200 focus-within:border-blue-500">
                <div className="py-3 px-4 bg-blue-100 border-r border-blue-200">
                    <Icon />
                </div>
                <div className="pr-4">
                    <select
                        name={name}
                        id={name}
                        ref={ref}
                        className="focus:outline-none pr-4"
                        value={value}
                        required
                        onChange={onChange}
                    >
                        <option disabled value="">
                            {placeholder}
                        </option>
                        {datas.map((data: any) => (
                            <option key={data.id} value={data.id}>
                                {`${data.name}`}
                            </option>
                        ))}
                    </select>
                </div>
            </div></>
    )
})



