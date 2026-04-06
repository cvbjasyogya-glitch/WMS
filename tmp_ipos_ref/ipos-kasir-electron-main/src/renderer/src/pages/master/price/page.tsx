import { FaCube, FaInfoCircle, FaSearch } from 'react-icons/fa';
import { InputText } from '../../../components/input/InputText';
import MainLayout from '../../../layout/MainLayout';
import { MasterLayout } from '../../../layout/MasterLayout';
import { useEffect, useRef, useState } from 'react';
import Dropdown from '../../../components/dropdown/DropDown';
import { handleCtrlE, handleCtrlF } from '../../../utils/keyboard';
import { InputSelect } from '../../../components/input/InputSelect';
import { LuNewspaper, LuSave } from 'react-icons/lu';
import { Button } from '../../../components/button/Button';
import { Message } from '../../../components/message/Message';
import { TableComponent } from '../../../components/table/TableComponent';
import { getDatasByField, handleDelete } from '../../../services/api';
import { MasterCallout } from '../../../components/callout/MasterCallout';
import { useNavigate } from 'react-router-dom';

export function MasterPrice() {
  const inputRef = useRef<HTMLInputElement>(null);
  const unitRef = useRef<HTMLSelectElement>(null);
  const [products, setProducts] = useState<any[]>([]);
  const [convertions, setConvertions] = useState<any[]>([]);
  const [units, setUnits] = useState<any[]>([]);
  const [selectedUnit, setSelectedUnit] = useState('');
  const [selectedProduct, setSelectedProduct] = useState<any>(null);
  const [isQuery, setIsQuery] = useState(false);
  const [highlightedIndex, setHighlightedIndex] = useState(-1);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [isEdit, setIsEdit] = useState(false);
  const navigate = useNavigate()
  const tableHead = ['no', 'units_name', 'sell_price', 'grosir', 'grosir_price'];
  const aliases = { no: 'No', units_name: 'Satuan', sell_price: 'Harga Jual', grosir: 'Grosir', grosir_price: 'Harga Grosir' };

  const handleFormSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const formData = new FormData(e.currentTarget);
    const data = Object.fromEntries(formData);
    const payload = {
      unit_id: Number(data.unit_id),
      sell_price: Number(data.purchase_price),
      product_id: selectedProduct.id
    };

    try {
      const response = await (window.api as any).convertion.post(payload);
      if (response.success) {
        await getDatasByField(selectedProduct.id, 'convertion', 'product_id', setConvertions);
        setSuccess('Data berhasil ditambahkan');
        setTimeout(() => setSuccess(''), 1000);
      } else {
        setError(response.error);
      }
    } catch (error) {
      setError(error as string);
    }
  };

  const handleDeleteConversion = async (id: number) => {
    const response = await handleDelete(id, 'convertion', setConvertions);
    if (response.success) {
      await getDatasByField(selectedProduct.id, 'convertion', 'product_id', setConvertions);
      setSuccess("Berhasil dihapus");
      setIsEdit(false);
      setTimeout(() => setSuccess(""), 1000);
    }
  };

  const handleSearch = async () => {
    setIsQuery(true);
    setHighlightedIndex(-1);
    const query = inputRef.current?.value || '';
    if (query) {
      const response = await (window.api as any).product.find(query);
      setProducts(response.data || []);
    } else {
      setProducts([]);
      setIsQuery(false);
    }
  };

  const handleSelectProduct = async (item: any) => {
    try {
      setIsQuery(false);
      const units = await (window.api as any).unit.get();
      setSelectedProduct(item);
      await getDatasByField(item.id, 'convertion', 'product_id', setConvertions);
      setUnits(units.data);
    } catch (error) {
      console.error(error);
    }
  };

  const handleKeyDown = (event: React.KeyboardEvent) => {
    switch (event.key) {
      case 'ArrowDown':
        setHighlightedIndex((prevIndex) => Math.min(prevIndex + 1, products.length - 1));
        break;
      case 'ArrowUp':
        setHighlightedIndex((prevIndex) => Math.max(prevIndex - 1, 0));
        break;
      case 'Enter':
        if (highlightedIndex >= 0) {
          inputRef.current!.value = '';
          inputRef.current!.blur();
          setTimeout(() => unitRef.current?.focus(), 1);
          handleSelectProduct(products[highlightedIndex]);
        }
        break;
      default:
        break;
    }
  };

  useEffect(() => {
    inputRef.current?.focus();
    const handler = (event: KeyboardEvent) => {
      handleCtrlF(event, inputRef);
      handleCtrlE(event, setIsEdit);
      if (event.ctrlKey && event.key.toLowerCase() === 'i') navigate('/master/import-price');
    };
    window.addEventListener('keydown', handler);
    return () => {
      window.removeEventListener('keydown', handler);
    };
  }, []);

  const message = 'Penggunaan satuan hanya untuk barang dengan <b>stok</b> yang <b>sama</b> dengan <b>harga berbeda</b>';

  const onCellSubmit = async (id: number, field: string, value: string) => {
    const payload = { [field]: value };
    try {
      const response = await (window as any).api.convertion.put(id, payload);
      if (response.success) {
        setSuccess('Data berhasil diupdate');
        setTimeout(() => setSuccess(''), 1000);
        await getDatasByField(selectedProduct.id, 'convertion', 'product_id', setConvertions);
        setIsEdit(false);
      } else {
        setError(response.error);
      }
    } catch (error) {
      setError(error as string);
      console.error(error);
    }
  };

  return (
    <MainLayout>
      <div className="bg-slate-100 min-h-[90vh] w-full">
        <MasterLayout title="Master Price" desc="Anda dapat update dan delete data harga">
          <div className="flex justify-between">
            <div className="w-1/3">
              <div className="flex items-center gap-x-4 w-full">
                <InputText
                  placeholder="Masukkan kode atau nama barang"
                  name="input"
                  label="input"
                  type="text"
                  outline="box"
                  icon={<FaSearch />}
                  ref={inputRef}
                  className="w-full rounded-md py-2 bg-blue-100/50"
                  onChange={handleSearch}
                  onKeyDown={handleKeyDown}
                />
                <div className="italic text-gray-500">{'(ctrl+f)'}</div>
              </div>
              <div className="w-[88%]">
                <Dropdown
                  items={products}
                  onSelect={handleSelectProduct}
                  isVisible={isQuery}
                  highlightedIndex={highlightedIndex}
                />
              </div>
            </div>
            <Button
              onClick={() => {
                navigate('/master/import-price');
              }}
              label={'Import Harga (ctrl+i)'}
              className="text-sm w-1/5"
              variant="success"
            />
          </div>
          <div className="py-4">
            {selectedProduct && (
              <div>
                <MasterCallout icon={<FaInfoCircle className='text-gray-500' />} message={message} />
                <div className="py-4">
                  <div className="font-semibold text-lg pb-2 mb-4 border-b">Tambah Harga</div>
                  <form onSubmit={handleFormSubmit} className='flex items-center gap-x-8'>
                    <InputSelect
                      ref={unitRef}
                      placeholder='Pilih satuan'
                      name='unit_id'
                      Icon={FaCube}
                      value={selectedUnit}
                      onChange={(e) => setSelectedUnit(e.target.value)}
                      datas={units}
                    />
                    <InputText
                      className='py-2'
                      placeholder='masukkan harga (Rp)'
                      name='purchase_price'
                      icon={<LuNewspaper />}
                      label='harga'
                      type='number'
                      outline='underline'
                    />
                    <Button label='Tambah' variant='default' size='medium' icon={<LuSave />} className='text-sm font-medium' />
                  </form>
                  <div>
                    {error && <Message text={error} variant='danger' onClick={() => setError('')} className='bg-red-100/70 border border-red-300 rounded-md px-4 py-2 w-fit' />}
                    {success && <Message text={success} variant='success' onClick={() => setSuccess('')} className='bg-green-100/70 border border-green-300 rounded-md px-4 py-2 w-fit' />}
                  </div>
                </div>
                <div className="py-4">
                  <div className="font-semibold text-lg pb-2 border-b">Daftar Harga</div>
                  <div className="pt-4 text-lg text-blue-500">
                    <div>Kode: <span className='font-bold'>{selectedProduct.barcode}</span></div>
                    <div>Barang: <span className='font-bold'>{selectedProduct.name}</span></div>
                  </div>
                  <div className="flex justify-end pb-4">
                    <Button label={isEdit ? 'Cancel (esc)' : 'Edit (ctrl+e)'} className='text-sm' variant='secondary' onClick={() => setIsEdit(!isEdit)} />
                  </div>
                  {convertions.length > 0 ? (
                    <TableComponent
                      onSelectChange={onCellSubmit}
                      onCellChange={onCellSubmit}
                      datas={convertions}
                      tableHead={tableHead}
                      aliases={aliases}
                      onDelete={handleDeleteConversion}
                      setIsEdit={setIsEdit}
                      isEdit={isEdit}
                    />
                  ) : (
                    <div className="text-gray-500 font-bold text-center bg-slate-100 border p-2">
                      Belum ada data harga
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </MasterLayout>
      </div>
    </MainLayout>
  );
}