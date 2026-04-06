import { FaSearch } from 'react-icons/fa';
import { InputText } from '../../components/input/InputText';
import MainLayout from '../../layout/MainLayout';
import { MasterLayout } from '../../layout/MasterLayout';
import { Button } from '../../components/button/Button';
import { useEffect, useRef, useState } from 'react';
import { useDispatch } from 'react-redux';
import { setTabIdx } from '../../reducers/tabReducer';
import { useNavigate } from 'react-router-dom';
import { TableComponent } from '../../components/table/TableComponent';
import { handleDelete, handleUpdate } from '../../services/api';
import { Message } from '../../components/message/Message';
import { Pagination } from '../../components/pagination/Pagination';
import { handleKeyDown } from '../../utils/utils';
import Dropdown from '../../components/dropdown/DropDown';
import { TbReload } from 'react-icons/tb';

export function MasterPage() {
  const [isEdit, setIsEdit] = useState(false);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const editRef = useRef<HTMLButtonElement | null>(null);
  const addRef = useRef<HTMLButtonElement | null>(null);
  const [datas, setDatas] = useState<any[]>([]);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [highlightedIndex, setHighlightedIndex] = useState(-1);
  const [isQuery, setIsQuery] = useState(false);
  const [_, setSelectedProduct] = useState<any>(null);
  const [products, setProducts] = useState<any[]>([]);

  const tableHead = ['no', 'barcode', 'name', 'purchase_price', 'categories_name', 'is_stock_variant'];
  const aliases = { no: 'No', barcode: 'Kode Barang', name: 'Nama Barang', purchase_price: 'Harga Beli', categories_name: 'Kategori', is_stock_variant: 'Tipe Stok' };

  const dispatch = useDispatch();
  const navigate = useNavigate();
  const LIMIT_PER_PAGE = 10;

  useEffect(() => {
    dispatch(setTabIdx(0));
  }, []);

  useEffect(() => {
    initProducts();
  }, [page]);

  useEffect(() => {
    const keyDownHandler = (event: KeyboardEvent) => {
      handleKeyDown(event, setIsEdit, navigate, inputRef);
      if (event.ctrlKey && event.key.toLowerCase() === 'i') navigate('/master/import');
    }
    document.addEventListener('keydown', keyDownHandler);
    return () => {
      document.removeEventListener('keydown', keyDownHandler);
    };
  }, [isEdit]);

  const initProducts = () => {
    getTotalPages()
      .then(() => getProducts())
      .catch((error) => console.error("Error fetching products:", error));
  };

  const getTotalPages = async () => {
    try {
      const totalRecordsResponse = await (window.api as any).product.count();
      if (totalRecordsResponse.success) {
        const totalPages = Math.ceil(totalRecordsResponse.data.count / LIMIT_PER_PAGE);
        setTotalPages(totalPages);
      }
    } catch (error) {
      console.error(error);
    }
  };

  const getProducts = async () => {
    try {
      const response = await (window.api as any).product.getPaginated(page, LIMIT_PER_PAGE);
      setDatas(response.data);
    } catch (error) {
      console.error(error);
    }
  };

  const handleDeleteData = async (id: number) => {
    const response = await handleDelete(id, 'product', setDatas);
    if (response.success) {
      setSuccess(true);
      setTimeout(() => setSuccess(false), 1000);
      initProducts();
      setIsEdit(false);
    }
  };

  const handleCellSubmit = async (id: any, field: any, value: any) => {
    try {
      const response = await handleUpdate('product', id, field, value);
      if (response.success) {
        initProducts();
        setIsEdit(false);
      }
    } catch (error) {
      console.error(error);
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

  const handleInputKeyDown = (event: React.KeyboardEvent) => {
    switch (event.key) {
      case 'ArrowDown':
        setHighlightedIndex(prevIndex => Math.min(prevIndex + 1, products.length - 1));
        break;
      case 'ArrowUp':
        setHighlightedIndex(prevIndex => Math.max(prevIndex - 1, 0));
        break;
      case 'Enter':
        if (highlightedIndex >= 0) {
          inputRef.current!.value = '';
          inputRef.current?.blur();
          setPage(1);
          handleSelectProduct(products[highlightedIndex]);
        }
        break;
      default:
        break;
    }
  };

  const handleSelectProduct = async (item: any) => {
    try {
      setIsQuery(false);
      setSelectedProduct(item);
      setDatas([item]);
    } catch (error) {
      console.error(error);
    }
  };

  return (
    <MainLayout>
      <div className="bg-slate-100 min-h-[90vh] w-full">
        <MasterLayout title="Master Product" desc="Anda dapat update dan delete data produk">
          <div className="flex flex-col gap-y-4">
            <div className="font-semibold text-lg pt-4 py-2 border-b">Daftar Produk</div>
            <div className="flex items-center justify-between">
              <div className="flex flex-col">
                <div className="w-full flex items-center gap-x-4">
                  <InputText
                    placeholder="Cari produk"
                    name="input"
                    label="input"
                    type="text"
                    outline="box"
                    icon={<FaSearch />}
                    ref={inputRef}
                    onChange={handleSearch}
                    onKeyDown={handleInputKeyDown}
                    className="w-full rounded-md py-2 bg-blue-100/50"
                  />
                  <div className="italic text-gray-500">{'(ctrl+f)'}</div>
                  <div className="ml-4">
                    <Button label="Reset" onClick={initProducts} icon={<TbReload />} />
                  </div>
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
              <div className="flex gap-x-2">
                <Button onClick={() => navigate('/master/import')} ref={addRef} label="Import (ctrl+i)" className="text-sm bg-green-500 hover:bg-green-600" />
                <Button onClick={() => navigate('/master/add-product')} ref={addRef} label="Tambah (ctrl+t)" className="text-sm" />
                <Button
                  ref={editRef}
                  onClick={() => setIsEdit(!isEdit)}
                  label={isEdit ? 'Batal (esc)' : 'Edit (ctrl+e)'}
                  className="text-sm"
                  variant="secondary"
                />
              </div>
            </div>
            <div>
              {success && <Message variant="success" text="Data berhasil dihapus" onClick={() => setSuccess(false)} className='bg-green-100/70 border border-green-300 rounded-md px-4 py-2 w-fit' />}
              {error && <Message variant="danger" text={error} onClick={() => setError("")} className='bg-red-100/70 border border-red-300 rounded-md px-4 py-2 w-fit' />}
            </div>
            <TableComponent onSelectChange={handleCellSubmit} onCellChange={handleCellSubmit} aliases={aliases} onDelete={handleDeleteData} tableHead={tableHead} datas={datas} isEdit={isEdit} setIsEdit={setIsEdit} />
          </div>
          <Pagination page={page} setPage={setPage} totalPages={totalPages} />
        </MasterLayout>
      </div>
    </MainLayout>
  );
}