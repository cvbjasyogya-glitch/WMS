import { useEffect, useRef, useState } from 'react';
import MainLayout from '../../../layout/MainLayout';
import { MasterLayout } from '../../../layout/MasterLayout';
import { InputText } from '../../../components/input/InputText';
import { Button } from '../../../components/button/Button';
import { Message } from '../../../components/message/Message';
import { TableComponent } from '../../../components/table/TableComponent';
import { FaAd, FaCubes, FaInfoCircle } from 'react-icons/fa';
import { MasterSection } from '../../../components/section/MasterSection';
import { MasterCallout } from '../../../components/callout/MasterCallout';
import { handleDelete, handleUpdate } from '../../../services/api';
import { handleCtrlE } from '../../../utils/keyboard';

export function MasterUnit() {
  const [datas, setDatas] = useState<any[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [isEdit, setIsEdit] = useState<boolean>(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const tableHead = ['no', 'name', 'factor'];
  const aliases = { no: 'No', name: 'Satuan', factor: 'Jumlah Barang' };

  useEffect(() => {
    fetchUnits();
    inputRef.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => handleCtrlE(event, setIsEdit);
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, []);

  const fetchUnits = async () => {
    try {
      const response = await (window.api as any).unit.get();
      setDatas(response.data);
    } catch (error) {
      console.error(error);
    }
  };

  const handleDeleteData = async (id: number) => {
    await handleDelete(id, 'unit', setDatas);
    fetchUnits();
    setSuccess('Data berhasil dihapus');
    setTimeout(() => setSuccess(null), 1000);
  };

  const handleSubmitForm = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const formData = new FormData(e.currentTarget);
    const payload = {
      name: String(formData.get('name')).toUpperCase(),
      factor: formData.get('factor'),
    };

    try {
      setLoading(true);
      const response = await (window.api as any).unit.post(payload);
      console.log(response)
      if (response.success) {
        setSuccess('Data berhasil ditambahkan');
        fetchUnits();
        e.currentTarget.reset();
        setTimeout(() => setSuccess(null), 1000);
      } else {
        setError(response.error);
      }
    } catch (error) {
      console.error(error);
    } finally {
      setLoading(false);
    }
  };

  const handleCellSubmit = async (id: any, field: any, value: any) => {
    try {
      const response = await handleUpdate('unit', id, field, value);
      console.log(response)
      if (response.success) {
        fetchUnits();
        setIsEdit(false);
      }
    } catch (error) {
      console.error(error);
    }
  };

  const message = 'Penggunaan satuan hanya untuk barang dengan <b>stok</b> yang <b>sama</b> dengan <b>harga berbeda</b>';

  return (
    <MainLayout>
      <div className="bg-slate-100 min-h-[90vh] w-full">
        <MasterLayout title="Master Satuan" desc="Anda dapat update dan delete data satuan">
          <MasterCallout icon={<FaInfoCircle className='text-gray-500' />} message={message} />
          <MasterSection text="Tambah Satuan" />
          <form onSubmit={handleSubmitForm}>
            <div className="flex gap-x-4">
              <div className="w-1/5">
                <InputText ref={inputRef} required placeholder="Nama Satuan" className='py-2' name="name" label="name" type="text" outline="underline" icon={<FaAd />} />
              </div>
              <div className="w-1/5">
                <InputText required placeholder="Jumlah Barang" className='py-2' name="factor" label="name" type="number" outline="underline" icon={<FaCubes />} />
              </div>
              <Button label='Tambah' disabled={loading} className='text-sm ' />
            </div>
          </form>
          {error && <Message text={error} variant='danger' onClick={() => setError('')} className='bg-red-100/70 border border-red-300 rounded-md px-4 py-2 w-fit' />}
          {success && <Message text={success} variant='success' onClick={() => setSuccess('')} className='bg-green-100/70 border border-green-300 rounded-md px-4 py-2 w-fit' />}
          <div className="flex justify-end">
            <Button label={isEdit ? 'Cancel (esc)' : 'Edit (ctrl+e)'} className='text-sm' variant='secondary' onClick={() => setIsEdit(!isEdit)} />
          </div>
          <div className="py-6">
            <TableComponent onCellChange={handleCellSubmit} onSelectChange={handleCellSubmit} aliases={aliases} onDelete={handleDeleteData} datas={datas} tableHead={tableHead} isEdit={isEdit} setIsEdit={setIsEdit} />
          </div>
        </MasterLayout>
      </div>
    </MainLayout>
  );
}