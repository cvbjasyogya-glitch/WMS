import { InputText } from '../../components/input/InputText'
import { LuBarcode, LuBox, LuDollarSign, LuNewspaper, LuSave, LuTag } from 'react-icons/lu'
import { Button } from '../../components/button/Button'
import { useEffect, useRef, useState } from 'react'
import { MasterLayout } from '../../layout/MasterLayout'
import MainLayout from '../../layout/MainLayout'
import { Message } from '../../components/message/Message'
import { InputSelect } from '../../components/input/InputSelect'
import { generateProductCode } from '../../utils/utils'

interface Props { }

interface PayloadData {
    category_id: number
    barcode: string
    name: string
    stock: number
    purchase_price: number
    is_stock_variant: number
}

const AddProduct: React.FC<Props> = () => {
    const [kategoriBarang, setKategoriBarang] = useState('');
    const [categories, setCategories] = useState([]);
    const [error, setError] = useState('');
    const [success, setSuccess] = useState('');
    const formRef = useRef<HTMLFormElement>(null)
    const [productCode, setProductCode] = useState('');
    const [isStockUnit, setIsStockUnit] = useState(0);

    const PostData = async (payload: PayloadData) => {
        try {
            const response = await (window.api as any).product.post(payload);
            console.log(response)
            if (response.success !== true) {
                setError(response.error)
            } else {
                formRef.current?.reset();
                setProductCode('')
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
            category_id: Number(formData.get('kategori_barang')) || 0,
            barcode: String(formData.get('kode_barang')) || '',
            name: String(formData.get('nama_barang')).toUpperCase() || '',
            stock: isStockUnit === 1 ? 0 : Number(formData.get('stok_barang')) || 0,
            is_stock_variant: isStockUnit || 0,
            purchase_price: Number(formData.get('harga_beli')) || 0
        };
        PostData(payload)
    }

    const getAllCategories = async () => {
        try {
            const response = await (window.api as any).category.get();
            setCategories(response.data)
        } catch (error) {
            console.log(error)
        }
    }

    useEffect(() => {
        getAllCategories()
    }, [])

    return (
        <MainLayout>
            <div className="bg-slate-100 min-h-screen">
                <MasterLayout title="Tambah barang" desc="Anda dapat menambahkan data barang" >
                    <div className="p-8 bg-slate-50 border">
                        <div className="py-4">
                            <div className="pb-4">
                                {success && <Message text={success} variant='success' onClick={() => setSuccess('')} className='bg-green-100/70 border border-green-300 rounded-md px-4 py-2 w-fit' />}
                                {error && <Message text={error} variant='danger' onClick={() => setError('')} className='bg-red-100/70 border border-red-300 rounded-md px-4 py-2 w-fit' />}
                            </div>
                            <form ref={formRef} action="" className="flex flex-col gap-y-3" onSubmit={SubmitForm}>
                                <div className="">
                                    <span className="text-sm text-red-500 font-semibold">Dibutuhkan*</span>
                                    <InputSelect placeholder='Kategori Barang' name='kategori_barang' Icon={LuTag} value={kategoriBarang} onChange={(e) => setKategoriBarang(e.target.value)} datas={categories} />
                                </div>
                                <div className="">
                                    <span className="text-sm text-red-500 font-semibold">
                                        {'Dibutuhkan*'}
                                        <span className="text-gray-500 font-semibold italic">
                                            {' (disarankan menggunakan barcode)'}
                                        </span>
                                    </span>
                                    <div className="flex items-center w-full gap-x-8">
                                        <InputText
                                            placeholder="Kode Barang"
                                            className="p-0 bg-white border-blue-200 w-1/2"
                                            name="kode_barang"
                                            label="kode_barang"
                                            type="text"
                                            value={productCode}
                                            outline="box"
                                            required={true}
                                            iconBgColor="py-3 px-4 bg-blue-100 border-r border-blue-200"
                                            icon={<LuBarcode />}
                                        />
                                        <Button
                                            label="Generate code"
                                            icon={<LuBarcode />}
                                            className="text-sm font-semibold"
                                            variant="default"
                                            size="medium"
                                            onClick={() => setProductCode(generateProductCode())}
                                        />
                                    </div>
                                </div>
                                <div className="">
                                    <span className="text-sm text-red-500 font-semibold">Dibutuhkan*</span>
                                    <InputText
                                        placeholder="Nama Barang"
                                        className="p-0 bg-white border-blue-200"
                                        name="nama_barang"
                                        label="nama_barang"
                                        type="text"
                                        required={true}
                                        outline="box"
                                        iconBgColor="py-3 px-4 bg-blue-100 border-r border-blue-200"
                                        icon={<LuNewspaper />}
                                    />
                                </div>
                                <div className="">
                                    <span className="text-sm text-red-500 font-semibold">Dibutuhkan*</span>
                                    <InputText
                                        placeholder="Harga Beli"
                                        className="p-0 bg-white border-blue-200"
                                        name="harga_beli"
                                        label="harga_beli"
                                        type="number"
                                        required={true}
                                        outline="box"
                                        iconBgColor="py-3 px-4 bg-blue-100 border-r border-blue-200"
                                        icon={<LuDollarSign />}
                                    />
                                </div>
                                <div className="">
                                    <span className="text-sm text-red-500 font-semibold">Pakai Stok Satuan ?*</span>
                                    <InputSelect
                                        Icon={LuBox}
                                        placeholder='Pilih'
                                        name='is_stock_variant'
                                        value={isStockUnit}
                                        onChange={(e) => setIsStockUnit(Number(e.target.value))}
                                        datas={[
                                            { id: 0, name: 'Tidak' },
                                            { id: 1, name: 'Ya' }
                                        ]}
                                    />
                                </div>
                                {isStockUnit != 1 && (
                                    <div className="">
                                        <span className="text-sm text-gray-500 font-semibold">
                                            Optional<span className="text-gray-500 font-normal italic">{' (default 0)'}</span>
                                        </span>
                                        <InputText
                                            placeholder="Stok Barang"
                                            className="p-0 bg-white border-blue-200"
                                            name="stok_barang"
                                            label="stok_barang"
                                            type="number"
                                            required={false}
                                            outline="box"
                                            iconBgColor="py-3 px-4 bg-blue-100 border-r border-blue-200"
                                            icon={<LuBox />}
                                        />
                                    </div>
                                )}
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

export { AddProduct }