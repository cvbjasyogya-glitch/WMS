import MainLayout from '../../../layout/MainLayout';
import { MasterLayout } from '../../../layout/MasterLayout';
import { useNavigate } from 'react-router-dom';
import { useEffect, useRef, useState } from 'react';
import { handleDelete, handleUpdate } from '../../../services/api';
import { FaBoxes, FaSearch } from 'react-icons/fa';
import { Button } from '../../../components/button/Button';
import { TableComponent } from '../../../components/table/TableComponent';
import { Message } from '../../../components/message/Message';
import { Pagination } from '../../../components/pagination/Pagination';
import { handleCtrlE, handleCtrlF } from '../../../utils/keyboard';
import { InputText } from '../../../components/input/InputText';
import { TbReload } from 'react-icons/tb';
import Dropdown from '../../../components/dropdown/DropDown';

export function MasterStock() {
  const [isEdit, setIsEdit] = useState(false);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [datas, setDatas] = useState<any[]>([]);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [highlightedIndex, setHighlightedIndex] = useState(-1);
  const [isQuery, setIsQuery] = useState(false);
  const [_, setSelectedProduct] = useState<any>(null);
  const [products, setProducts] = useState<any[]>([]);

  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const editRef = useRef<HTMLButtonElement | null>(null);
  const LIMIT_PER_PAGE = 10;

  const tableHead = ['no', 'name', 'stock', 'is_stock_variant'];
  const aliases = { no: 'No', name: 'Nama Barang', stock: 'Stok', is_stock_variant: 'Tipe Stok' };

  useEffect(() => {
    initProducts();
  }, []);

  useEffect(() => {
    getProducts();
  }, [page]);

  useEffect(() => {
    const keyDownHandler = (event: KeyboardEvent) => {
      handleCtrlE(event, setIsEdit);
      handleCtrlF(event, inputRef);
      if (event.ctrlKey && event.key.toLowerCase() === 'i') navigate('/master/import-stock');
    };
    document.addEventListener('keydown', keyDownHandler);
    return () => {
      document.removeEventListener('keydown', keyDownHandler);
    };
  }, [isEdit]);

  const initProducts = () => {
    fetchTotalPages()
      .then(() => getProducts())
      .catch((error) => console.error("Error fetching products:", error));
  };

  const fetchTotalPages = async () => {
    try {
      const response = await (window.api as any).product.count();
      if (response.success) {
        const totalPages = Math.ceil(response.data.count / LIMIT_PER_PAGE);
        totalPages && setTotalPages(totalPages);
      }
    } catch (error) {
      console.error("Error fetching total pages:", error);
    }
  };

  const getProducts = async () => {
    try {
      const response = await (window.api as any).product.getPaginated(page, LIMIT_PER_PAGE);
      setDatas(response.data);
    } catch (error) {
      console.error("Error fetching products:", error);
    }
  };

  const deleteData = async (id: number) => {
    try {
      const response = await handleDelete(id, 'product', setDatas);
      if (response.success) {
        setSuccess(true);
        setTimeout(() => setSuccess(false), 1000);
        await getProducts();
      }
    } catch (error) {
      console.error("Error deleting data:", error);
    }
  };

  const onCellSubmit = async (id: any, field: any, value: any) => {
    try {
      const response = await handleUpdate('product', id, field, value);
      if (response.success) {
        await getProducts();
        setIsEdit(false);
      }
    } catch (error) {
      console.error("Error updating cell:", error);
    }
  };

  const rowEnter = (id: number) => {
    navigate(`/master/add-stock/${id}`);
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
        <MasterLayout title="Master Stock" desc="Anda dapat update dan delete data stock">
          <div className="flex flex-col gap-y-4">
            <div className="font-semibold text-lg pt-4 py-2 border-b">Daftar Produk</div>
            <div className="w-[50%] flex flex-col items-center gap-x-4">
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
              <div className="ml-[-4rem] w-[88%]">
                <Dropdown
                  items={products}
                  onSelect={handleSelectProduct}
                  isVisible={isQuery}
                  highlightedIndex={highlightedIndex}
                />
              </div>
            </div>
            <div className="flex gap-x-4 items-center justify-end">
              <Button
                ref={editRef}
                onClick={() => {
                  navigate('/master/import-stock');
                }}
                label={'Import Stock (ctrl+i)'}
                className="text-sm"
                variant="success"
              />
              <Button
                ref={editRef}
                onClick={() => {
                  setIsEdit(!isEdit);
                  editRef.current?.blur();
                }}
                label={isEdit ? 'Batal (esc)' : 'Update stock (ctrl+e)'}
                icon={<FaBoxes />}
                className="text-sm"
                variant="secondary"
              />
            </div>
            <div>
              {success && (
                <Message
                  variant="success"
                  text="Data berhasil dihapus"
                  onClick={() => setSuccess(false)}
                  className="bg-green-100/70 border border-green-300 rounded-md px-4 py-2 w-fit"
                />
              )}
              {error && (
                <Message
                  variant="danger"
                  text={error}
                  onClick={() => setError("")}
                  className="bg-red-100/70 border border-red-300 rounded-md px-4 py-2 w-fit"
                />
              )}
            </div>
            <TableComponent
              rowEnter={rowEnter}
              onSelectChange={onCellSubmit}
              onCellChange={onCellSubmit}
              aliases={aliases}
              onDelete={deleteData}
              tableHead={tableHead}
              datas={datas}
              isEdit={isEdit}
              setIsEdit={setIsEdit}
            />
          </div>
          <Pagination page={page} setPage={setPage} totalPages={totalPages} />
        </MasterLayout>
      </div>
    </MainLayout>
  );
}