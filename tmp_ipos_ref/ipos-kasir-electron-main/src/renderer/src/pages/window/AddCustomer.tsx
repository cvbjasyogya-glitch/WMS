import { InputText } from '../../components/input/InputText'
import { LuMapPin, LuPhone, LuSave, LuUser } from 'react-icons/lu'
import { Button } from '../../components/button/Button'
import { useEffect, useRef, useState } from 'react'
import { MasterLayout } from '../../layout/MasterLayout'
import MainLayout from '../../layout/MainLayout'
import { Message } from '../../components/message/Message'
import { useNavigate } from 'react-router-dom'
import { handleEsc } from '../../utils/keyboard'

interface PayloadData {
    name: string;
    phone: string | null;
    address: string | null;
}

export const AddCustomer: React.FC = () => {
    const [error, setError] = useState('');
    const [success, setSuccess] = useState('');
    const formRef = useRef<HTMLFormElement>(null)
    const navigate = useNavigate()

    const PostData = async (payload: PayloadData) => {
        try {
            const response = await (window.api as any).customer.post(payload);
            console.log(response)
            if (response.success !== true) {
                setError(response.error)
            } else {
                formRef.current?.reset();
                setSuccess("Data berhasil ditambahkan")
                setTimeout(() => {
                    setSuccess('')
                }, 700)
            }
        } catch (error) {
            setError(error as string)
        }
    }
    const SubmitForm = async (e: React.FormEvent<HTMLFormElement>) => {
        e.preventDefault()
        const formData = new FormData(e.currentTarget)
        const payload: PayloadData = {
            name: String(formData.get('name')).toUpperCase() || '',
            phone: String(formData.get('phone')) || null,
            address: String(formData.get('address')) || null,
        };
        PostData(payload)
    }

    useEffect(() => {
        window.addEventListener('keydown', (e) => handleEsc(e, () => navigate('/point')))
        return () => {
            window.removeEventListener('keydown', (e) => handleEsc(e, () => navigate('/point')))
        }
    }, [])

    return (
        <MainLayout>
            <div className="bg-slate-100 min-h-screen">
                <MasterLayout title="Tambah pembeli" desc="Anda dapat menambahkan data pembeli" >
                    <div className="p-8 bg-slate-50 border">
                        <div className="py-4">
                            <div className="pb-4">
                                {success && <Message text={success} variant='success' onClick={() => setSuccess('')} className='bg-green-100/70 border border-green-300 rounded-md px-4 py-2 w-fit' />}
                                {error && <Message text={error} variant='danger' onClick={() => setError('')} className='bg-red-100/70 border border-red-300 rounded-md px-4 py-2 w-fit' />}
                            </div>
                            <form ref={formRef} action="" className="flex flex-col gap-y-3" onSubmit={SubmitForm}>
                                <div className="">
                                    <span className="text-sm text-red-500 font-semibold">Dibutuhkan*</span>
                                    <InputText
                                        placeholder="Nama Pembeli"
                                        className="p-0 bg-white border-blue-200"
                                        name="name"
                                        label="name"
                                        type="text"
                                        required={true}
                                        outline="box"
                                        iconBgColor="py-3 px-4 bg-blue-100 border-r border-blue-200"
                                        icon={<LuUser />}
                                    />
                                </div>
                                <div className="">
                                    <span className="text-sm text-gray-500 font-semibold">
                                        Optional
                                    </span>
                                    <InputText
                                        placeholder="Telepon"
                                        className="p-0 bg-white border-blue-200"
                                        name="phone"
                                        label="phone"
                                        type="text"
                                        required={false}
                                        outline="box"
                                        iconBgColor="py-3 px-4 bg-blue-100 border-r border-blue-200"
                                        icon={<LuPhone />}
                                    />
                                </div>
                                <div className="">
                                    <span className="text-sm text-gray-500 font-semibold">
                                        Optional
                                    </span>
                                    <InputText
                                        placeholder="Alamat"
                                        className="p-0 bg-white border-blue-200"
                                        name="address"
                                        label="address"
                                        type="text"
                                        required={false}
                                        outline="box"
                                        iconBgColor="py-3 px-4 bg-blue-100 border-r border-blue-200"
                                        icon={<LuMapPin />}
                                    />
                                </div>
                                <div className="py-4 flex justify-end">
                                    <Button
                                        label="Simpan"
                                        icon={<LuSave />}
                                        className="text-sm font-semibold"
                                        variant="default"
                                        size="medium"
                                    />
                                </div>
                            </form>
                        </div>
                    </div>
                </MasterLayout>
            </div>
        </MainLayout>
    )
}

