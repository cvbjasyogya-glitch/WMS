import { InputText } from '../../components/input/InputText';
import { LuBox, LuCalendar, LuSave, LuTag, LuTruck } from 'react-icons/lu';
import { Button } from '../../components/button/Button';
import { useEffect, useRef, useState } from 'react';
import { MasterLayout } from '../../layout/MasterLayout';
import MainLayout from '../../layout/MainLayout';
import { Message } from '../../components/message/Message';
import { useParams } from 'react-router-dom';
import { InputSelect } from '../../components/input/InputSelect';

interface Props { }

const AddStock: React.FC<Props> = () => {
    const { id: productId } = useParams<{ id: string }>();
    const [category, setSelectedCategory] = useState('');
    const [convertions, setConvertions] = useState<any[]>([]);
    const [product, setProduct] = useState<any>({});
    const [units, setUnits] = useState<[]>([]);
    const [error, setError] = useState('');
    const [success, setSuccess] = useState('');
    const formRef = useRef<HTMLFormElement>(null);

    const UpdateData = async (id: number, section: string, payload: any) => {
        console.log(section, id)
        try {
            const response = await (window as any).api[section].putMany(['id'], payload);
            console.log(response)
            if (response.success !== true) {
                throw new Error(response.error);
            }
            return response;
        } catch (error) {
            setError(error instanceof Error ? error.message : String(error));
        }
    };

    const SubmitForm = async (e: React.FormEvent<HTMLFormElement>) => {
        e.preventDefault();
        const formData = new FormData(e.currentTarget);
        const selectedUnitId = Number(formData.get('convertion_id'));
        const inputStock = Number(formData.get('stock'));
        const currentConversion = convertions.find(item => item.id === selectedUnitId);

        let payload = [{ id: selectedUnitId, stock: inputStock }];
        try {
            if (product.is_stock_variant === 1) {
                console.log('masuk variant');
                const response = await UpdateData(selectedUnitId, 'convertion', payload);
                if (!response.success) throw new Error(response.error);
                await handleInbound(formData, inputStock, currentConversion);
            } else {
                console.log('masuk produk');
                payload = [{ id: Number(productId), stock: inputStock }];
                const response = await UpdateData(Number(productId), 'product', payload);
                if (!response.success) throw new Error(response.error);
                await handleInbound(formData, inputStock, currentConversion);
            }
            formRef.current?.reset();
        } catch (error) {
            setError(error instanceof Error ? error.message : String(error));
        }
    };

    const handleInbound = async (formData: FormData, inputStock: number, currentConversion?: any) => {
        try {
            const response = await (window.api as any).inbound.postMany([{
                product_id: Number(productId),
                received_date: formData.get('received_date'),
                quantity: inputStock,
                supplier: formData.get('supplier') || '',
                unit_id: currentConversion.units_id || null
            }]);
            if (!response.success) throw new Error(response.error);
            setSuccess("Data berhasil ditambahkan");
            setTimeout(() => setSuccess(''), 700);
        } catch (error) {
            setError(error instanceof Error ? error.message : String(error));
        }
    };

    const getConvertions = async () => {
        try {
            const response = await (window.api as any).convertion.getByField('product_id', productId);
            const productResponse = await (window.api as any).product.get(productId);
            if (!response || !productResponse) throw new Error('Data tidak ditemukan');
            if (response.success) {
                setConvertions(response.data);
                setProduct(productResponse.data);
                const units = response.data.map(item => ({
                    id: item.id,
                    name: item.units_name,
                    unit_id: item.unit_id,
                }));
                setUnits(units);
            }
        } catch (error) {
            setError(error instanceof Error ? error.message : String(error));
        }
    };

    useEffect(() => {
        getConvertions();
    }, [success]);

    return (
        <MainLayout >
            <div className="bg-slate-100 min-h-screen">
                <MasterLayout title="Tambah stok" desc="Anda dapat menambahkan data stok">
                    <div className="p-8 bg-slate-50 border">
                        <div className="">
                            <div className="flex gap-x-2 border-2 p-2 mb-2 bg-white w-fit">
                                <div className="text-lg text-blue-500 font-bold">{product.name}</div>
                                <div className="text-lg text-blue-500 font-bold">{`- ${product.barcode}`}</div>
                            </div>
                            <div className="text-lg text-blue-500 font-bold p-2 bg-white w-fit border-2">{`[total stok: ${product.stock} ]`}</div>
                        </div>
                        {product && product.is_stock_variant == 1 &&
                            <table className='w-1/2 mt-2 text-lg'>
                                <thead>
                                    <tr>
                                        <th className="border bg-blue-400 text-white px-4 py-1">Satuan</th>
                                        <th className="border bg-blue-400 text-white px-4 py-1">Jumlah</th>
                                        <th className="border bg-blue-400 text-white px-4 py-1">Stok</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {convertions.map((item: any, index: number) => (
                                        <tr key={index}>
                                            <td className="border bg-white px-4 py-1">{item.units_name}</td>
                                            <td className="border bg-white px-4 py-1">{item.units_factor}</td>
                                            <td className="border bg-white px-4 py-1">{item.stock}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        }
                        <div className="py-4">
                            <div className="pb-4">
                                {success && <Message text={success} variant='success' onClick={() => setSuccess('')} className='bg-green-100/70 border border-green-300 rounded-md px-4 py-2 w-fit' />}
                                {error && <Message text={error} variant='danger' onClick={() => setError('')} className='bg-red-100/70 border border-red-300 rounded-md px-4 py-2 w-fit' />}
                            </div>
                            <form ref={formRef} className="flex flex-col gap-y-3" onSubmit={SubmitForm}>
                                <div className="">
                                    <span className="text-sm text-red-500 font-semibold">Dibutuhkan*</span>
                                    <InputSelect placeholder='Pilih Satuan' name='convertion_id' Icon={LuTag} value={category} onChange={(e) => setSelectedCategory(e.target.value)} datas={units} />
                                </div>
                                <div className="w-1/5">
                                    <span className="text-sm text-red-500 font-semibold">{'Jumlah Barang*'}</span>
                                    <InputText
                                        placeholder="Tambah Stok Barang"
                                        className="p-0 bg-white border-blue-200"
                                        name="stock"
                                        label="stok"
                                        type="number"
                                        outline="box"
                                        required={true}
                                        iconBgColor="py-3 px-4 bg-blue-100 border-r border-blue-200"
                                        icon={<LuBox />}
                                    />
                                </div>
                                <div className="w-1/5">
                                    <span className="text-sm text-red-500 font-semibold">{'Tanggal Input Barang*'}</span>
                                    <InputText
                                        placeholder="Tanggal Input"
                                        className="p-0 pr-2 bg-white border-blue-200"
                                        name="received_date"
                                        label="received_date"
                                        type="datetime-local"
                                        outline="box"
                                        required={true}
                                        iconBgColor="py-3 px-4 bg-blue-100 border-r border-blue-200"
                                        icon={<LuCalendar />}
                                    />
                                </div>
                                <div className="w-1/5">
                                    <span className="text-sm text-black font-semibold">{'Supplier (opsional)'}</span>
                                    <InputText
                                        placeholder="Supplier"
                                        className="p-0 pr-2 bg-white border-blue-200"
                                        name="supplier"
                                        label="supplier"
                                        type="text"
                                        outline="box"
                                        iconBgColor="py-3 px-4 bg-blue-100 border-r border-blue-200"
                                        icon={<LuTruck />}
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
        </MainLayout >
    );
};

export { AddStock };