import { useEffect, useRef, useState } from 'react'
import Layout from '../../layout/MainLayout'
import { TableComponent } from '../../components/table/TableComponent'
import { handleDelete, handleUpdate } from '../../services/api'
import { InputText } from '../../components/input/InputText'
import { FaSearch } from 'react-icons/fa'
import { Button } from '../../components/button/Button'
import { useNavigate } from 'react-router-dom'
import { handleCtrlE, handleCtrlF, handleCtrlT } from '../../utils/keyboard'

export function PointPage() {
  const [isEdit, setIsEdit] = useState(false)
  const [_, setSuccess] = useState('')
  const [datas, setDatas] = useState<any[]>([])
  const addRef = useRef<HTMLButtonElement | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const editRef = useRef<HTMLButtonElement | null>(null);
  const navigate = useNavigate();

  const tableHead = ['no', 'name', 'phone', 'address', 'points']
  const aliases = { no: 'No', name: 'Nama', phone: 'Telepon', address: 'Alamat', points: 'Poin' }
  const fetchCustomers = async () => {
    try {
      const response = await (window as any).api.customer.get()
      setDatas(response.data)
    } catch (error) {
      console.log(error)
    }
  }

  const deleteData = async (id: number) => {
    const response = await handleDelete(id, 'customer', setDatas);
    console.log(response)
    fetchCustomers();
    setIsEdit(false);
    setSuccess('Data berhasil dihapus');
    setTimeout(() => {
      setSuccess('');
    }, 1000)
  };

  const handleCellSubmit = async (id: any, field: any, value: any) => {
    try {
      console.log(id, field, value)
      const response = await handleUpdate('customer', id, field, value);
      console.log(response)
      if (response.success) {
        fetchCustomers();
        setIsEdit(false);
      }
    } catch (error) {
      console.log(error);
    }
  };

  useEffect(() => {
    const handlerKey = (e: any) => {
      handleCtrlE(e, setIsEdit)
      handleCtrlF(e, inputRef)
      handleCtrlT(e, () => navigate('/point/add-customer'))
      if (e.ctrlKey && e.key.toLowerCase() === 'i') navigate('/point/import-customer');
    }
    fetchCustomers()
    window.addEventListener('keydown', handlerKey)
    return () => {
      window.removeEventListener('keydown', handlerKey)
    }
  }, [])

  return (
    <Layout>
      <div className="flex  bg-slate-100 min-h-[90vh] w-full pt-6 ">
        <div className="w-full px-4">
          <div className="bg-white p-8 w-full shadow border">
            <div className="text-xl font-semibold">Customer</div>
            <div className="w-full flex items-center gap-x-4 py-8">
              <InputText
                placeholder="Cari customer"
                name="input"
                label="input"
                type="text"
                outline="box"
                icon={<FaSearch />}
                ref={inputRef}
                className=" rounded-md py-2 bg-blue-100/50 w-1/3"
              />
              <div className="flex w-full justify-end ">
                <div className="flex  gap-x-4">
                  <Button
                    onClick={() => {
                      navigate('/point/import-customer');
                    }}
                    label={'Import Pembeli (ctrl+i)'}
                    className="text-sm"
                    variant="success"
                  />
                  <Button onClick={() => navigate('/point/add-customer')} ref={addRef} label="Tambah (ctrl+t)" className="text-sm" />
                  <Button
                    ref={editRef}
                    onClick={() => setIsEdit(!isEdit)}
                    label={isEdit ? 'Batal (esc)' : 'Edit (ctrl+e)'}
                    className="text-sm"
                    variant="secondary"
                  />
                </div>
              </div>
            </div>
            {/* Table */}
            <TableComponent datas={datas} tableHead={tableHead} aliases={aliases} onCellChange={handleCellSubmit} onSelectChange={handleCellSubmit} onDelete={deleteData} isEdit={isEdit} setIsEdit={setIsEdit} />
          </div>
        </div>
      </div>
    </Layout>
  )
}
