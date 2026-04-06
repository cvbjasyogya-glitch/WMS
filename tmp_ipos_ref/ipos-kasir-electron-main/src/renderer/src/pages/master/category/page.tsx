import { useEffect, useRef, useState } from 'react';
import { FaAd, FaTag } from 'react-icons/fa';
import MainLayout from '../../../layout/MainLayout';
import { MasterLayout } from '../../../layout/MasterLayout';
import { Button } from '../../../components/button/Button';
import { InputText } from '../../../components/input/InputText';
import { Message } from '../../../components/message/Message';
import { TableComponent } from '../../../components/table/TableComponent';
import { handleDelete, handleUpdate } from '../../../services/api';
import { MasterSection } from '../../../components/section/MasterSection';
import { useDispatch } from 'react-redux';
import { setTabIdx } from '../../../reducers/tabReducer';
import { handleCtrlE } from '../../../utils/keyboard';

export function MasterCategory() {
  const [isEdit, setIsEdit] = useState(false);
  const [datas, setDatas] = useState<any[]>([]);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [loading, setLoading] = useState(false);
  const dispatch = useDispatch();

  const codeInputRef = useRef<HTMLInputElement>(null);
  const nameInputRef = useRef<HTMLInputElement>(null);

  const tableHead = ['no', 'code', 'name'];
  const aliases = { no: 'No', code: 'Kode', name: 'Kategori' };

  useEffect(() => {
    fetchCategories();
    dispatch(setTabIdx(3));
    codeInputRef.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => handleCtrlE(event, setIsEdit);
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [dispatch]);

  const fetchCategories = async () => {
    try {
      const response = await (window.api as any).category.get();
      if (response.success) {
        setDatas(response.data);
      }
    } catch (error) {
      console.error(error);
    }
  };

  const handleDeleteData = async (id: number) => {
    await handleDelete(id, 'category', setDatas);
    setSuccess('Data berhasil dihapus');
    setTimeout(() => setSuccess(''), 1000);
    fetchCategories();
  };

  const handleSubmitForm = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const formData = new FormData(e.currentTarget);
    const payload = {
      code: String(formData.get('kode_category')).toUpperCase().replace(/\s+/g, '') || '',
      name: String(formData.get('nama_category')).toUpperCase() || '',
    };

    try {
      setLoading(true);
      const response = await (window.api as any).category.post(payload);
      if (response.success) {
        setSuccess('Kategori berhasil ditambahkan!');
        resetForm();
        fetchCategories();
      } else {
        setError(response.error || 'Unknown error');
      }
    } catch (error) {
      setError(error as string);
    } finally {
      setLoading(false);
    }
  };

  const resetForm = () => {
    if (codeInputRef.current) codeInputRef.current.value = '';
    if (nameInputRef.current) nameInputRef.current.value = '';
  };

  const handleCellSubmit = async (id: any, field: any, value: any) => {
    try {
      const response = await handleUpdate('category', id, field, value);
      if (response.success) {
        fetchCategories();
        setIsEdit(false);
      }
    } catch (error) {
      console.error(error);
    }
  };

  return (
    <MainLayout>
      <div className="bg-slate-100 min-h-[90vh] w-full">
        <MasterLayout title="Master Kategori" desc="Anda dapat update dan delete data kategori">
          <MasterSection text='Tambah Kategori' />
          <form onSubmit={handleSubmitForm}>
            <div className="flex gap-x-4">
              <div className="w-1/5">
                <InputText
                  ref={codeInputRef}
                  required
                  placeholder="Kode Kategori"
                  className='py-2'
                  name="kode_category"
                  label="name"
                  type="text"
                  outline="underline"
                  icon={<FaTag />}
                />
              </div>
              <div className="w-1/3">
                <InputText
                  ref={nameInputRef}
                  required
                  placeholder="Nama Kategori"
                  className='py-2'
                  name="nama_category"
                  label="name"
                  type="text"
                  outline="underline"
                  icon={<FaAd />}
                />
              </div>
              <Button label='Tambah' disabled={loading} className='text-sm' />
            </div>
          </form>
          {error && (
            <Message
              text={error}
              variant='danger'
              onClick={() => setError('')}
              className='bg-red-100/70 border border-red-300 rounded-md px-4 py-2 w-fit'
            />
          )}
          {success && (
            <Message
              text={success}
              variant='success'
              onClick={() => setSuccess('')}
              className='bg-green-100/70 border border-green-300 rounded-md px-4 py-2 w-fit'
            />
          )}
          <div className="flex justify-end">
            <Button
              label={isEdit ? 'Cancel (esc)' : 'Edit (ctrl+e)'}
              className='text-sm'
              variant='secondary'
              onClick={() => setIsEdit(!isEdit)}
            />
          </div>
          <div className="py-6">
            <TableComponent
              onCellChange={handleCellSubmit}
              onSelectChange={handleCellSubmit}
              aliases={aliases}
              onDelete={handleDeleteData}
              datas={datas}
              tableHead={tableHead}
              isEdit={isEdit}
              setIsEdit={setIsEdit}
            />
          </div>
        </MasterLayout>
      </div>
    </MainLayout>
  );
} 