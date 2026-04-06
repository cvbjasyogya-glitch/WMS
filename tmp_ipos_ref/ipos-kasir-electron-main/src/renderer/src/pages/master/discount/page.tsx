import { MasterSection } from "../../../components/section/MasterSection";
import MainLayout from "../../../layout/MainLayout";
import { MasterLayout } from "../../../layout/MasterLayout";
import { InputText } from "../../../components/input/InputText";
import { FaAd, FaPercent } from "react-icons/fa";
import { useEffect, useState } from "react";
import { Button } from "../../../components/button/Button";
import { TableComponent } from "../../../components/table/TableComponent";
import { Message } from "../../../components/message/Message";
import { handleCtrlE } from "../../../utils/keyboard";
import { handleUpdate } from "../../../services/api";

export function MasterDiscount() {
    const [loading, setLoading] = useState(false);
    const [isEdit, setIsEdit] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [datas, setDatas] = useState<any[]>([]);
    const tableHead = ['no', 'name', 'value'];
    const aliases = { no: 'No', name: 'Nama', value: 'Nilai' };
    const [success, setSuccess] = useState<string | null>(null);

    const deleteData = async (id: number) => {
        try {
            const response = await (window.api as any).discount.delete(id);
            if (response.success == true) {
                setSuccess("Berhasil dihapus");
                setIsEdit(false)
                setTimeout(() => {
                    setSuccess("");
                }, 1000);
                fetchDiscounts()
            }
        } catch (error) {
            setError(error as string)
        }
    }

    const SubmitForm = async (e: React.FormEvent<HTMLFormElement>) => {
        e.preventDefault();
        const formData = new FormData(e.currentTarget);
        const data = Object.fromEntries(formData);
        const payload = {
            name: String(data.name).toUpperCase(),
            value: Number(data.value)
        }

        try {
            setLoading(true);
            const response = await (window.api as any).discount.post(payload);
            if (response.success != true) {
                setLoading(false)
                setError(response.error)
            } else {
                setLoading(false)
                setSuccess('Data berhasil ditambahkan')
                setTimeout(() => {
                    setSuccess('')
                }, 1000)
                fetchDiscounts();
                (e.currentTarget as HTMLFormElement).reset();
            }
        } catch (error) {
            console.log(error)
        }
    }

    const fetchDiscounts = async () => {
        try {
            const response = await (window.api as any).discount.get();
            setDatas(response.data)
        } catch (error) {
            setError(error as string)
        }
    }

    const onCellSubmit = async (id: any, field: any, value: any) => {
        try {
            const response = await handleUpdate('category', id, field, value);
            if (response.success) {
                fetchDiscounts();
                setIsEdit(false);
            }
        } catch (error) {
            console.log(error);
        }
    };

    useEffect(() => {
        fetchDiscounts()
    }, [])

    useEffect(() => {
        document.addEventListener('keydown', (event) => handleCtrlE(event, setIsEdit));
        return () => document.removeEventListener('keydown', (event) => handleCtrlE(event, setIsEdit));
    }, [isEdit]);

    return (
        <MainLayout>
            <div className="bg-slate-100 min-h-screen">
                <MasterLayout title="Master Discount" desc="Anda dapat update dan delete data discount">
                    <MasterSection text="Tambah Discount" />
                    <div className="">
                        <form className="" onSubmit={SubmitForm}>
                            <div className="flex gap-x-4">
                                <div className="w-1/5">
                                    <InputText required={true} placeholder="Nama Diskon" className='py-2' name="name" label="name" type="text" outline="underline" icon={<FaAd />} />
                                </div>
                                <div className="w-1/5">
                                    <InputText required={true} placeholder="Nilai Diskon (persen)" className='py-2' name="value" label="name" type="number" outline="underline" icon={<FaPercent />} />
                                </div>
                                <Button label='Tambah' disabled={loading} className='text-sm' />
                            </div>
                        </form>
                    </div>
                    {error && <Message text={error} variant='danger' onClick={() => setError('')} className='bg-red-100/70 border border-red-300 rounded-md px-4 py-2 w-fit' />}
                    {success && <Message text={success} variant='success' onClick={() => setSuccess('')} className='bg-green-100/70 border border-green-300 rounded-md px-4 py-2 w-fit' />}
                    <div className="flex justify-end">
                        <Button label={isEdit ? 'Cancel (esc)' : 'Edit (ctrl+e)'} className='text-sm' variant='secondary' onClick={() => setIsEdit(!isEdit)} />
                    </div>
                    <div className="py-6">
                        <TableComponent onCellChange={onCellSubmit} onSelectChange={onCellSubmit} aliases={aliases} onDelete={deleteData} datas={datas} tableHead={tableHead} isEdit={isEdit} setIsEdit={setIsEdit} />
                    </div>
                </MasterLayout>
            </div>
        </MainLayout>
    )
}