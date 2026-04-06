import { useEffect, useRef, useState } from 'react';
import Layout from '../../layout/MainLayout';
import { TableComponent } from '../../components/table/TableComponent';
import { InputText } from '../../components/input/InputText';
import { FaArrowRight, FaCalendarAlt, FaSearch } from 'react-icons/fa';
import { TbReload } from "react-icons/tb";
import { useNavigate } from 'react-router-dom';
import { handleCtrlF, handleCtrlT } from '../../utils/keyboard';
import { Button } from '../../components/button/Button';
import { Pagination } from '../../components/pagination/Pagination';
import Dropdown from '../../components/dropdown/DropDown';

export function OutboundPage() {
  const [isEdit, setIsEdit] = useState(false);
  const [datas, setDatas] = useState<any[]>([]);
  const [page, setPage] = useState(1);
  const [products, setProducts] = useState<any[]>([]);
  const [selectedProduct, setSelectedProduct] = useState<any>(null);
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [isQuery, setIsQuery] = useState(false);
  const [highlightedIndex, setHighlightedIndex] = useState(-1);
  const [totalPages, setTotalPages] = useState(1);
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  const tableHead = ['no', 'products_barcode', 'products_name', 'product_qty', 'units_name', 'order_date'];
  const aliases = { no: 'No', products_barcode: 'Barcode', products_name: 'Barang', product_qty: 'Jumlah', units_name: 'Satuan', order_date: 'Tanggal' };
  const LIMIT_PER_PAGE = 10;

  useEffect(() => {
    getTotalPages().then(() => fetchTransactions());
    const handlerKey = (e: KeyboardEvent) => {
      handleCtrlF(e, inputRef);
      handleCtrlT(e, () => navigate('/point/add-customer'));
    };
    window.addEventListener('keydown', handlerKey);
    return () => {
      window.removeEventListener('keydown', handlerKey);
    };
  }, [navigate, page, selectedProduct, start, end]);

  const filterDate = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const formData = new FormData(e.currentTarget);
    const start = formData.get('start_date');
    const end = formData.get('end_date');
    setStart(start as string);
    setEnd(end as string);
  };

  const fetchTransactions = async () => {
    try {
      let response: any;
      if (selectedProduct) {
        response = await (window.api as any).transaction.getPaginated(page, LIMIT_PER_PAGE, selectedProduct.id, 'product_id', 'order_date', start, end);
      } else {
        response = await (window.api as any).transaction.getPaginated(page, LIMIT_PER_PAGE, -1, null, 'order_date', start, end);
      }
      setDatas(response.data);
    } catch (error) {
      console.error(error);
    }
  };

  const getTotalPages = async () => {
    try {
      let id = selectedProduct ? selectedProduct.id : -1
      let field = selectedProduct ? 'product_id' : null
      const totalRecordsResponse = await (window.api as any).transaction.count(id, field, 'order_date', start, end);
      if (totalRecordsResponse.success) {
        const totalPages = Math.ceil(totalRecordsResponse.data.count / LIMIT_PER_PAGE);
        setTotalPages(totalPages);
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

  const handleKeyDown = (event: React.KeyboardEvent) => {
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
    } catch (error) {
      console.error(error);
    }
  };

  return (
    <Layout>
      <div className="flex bg-slate-100 min-h-[90vh] w-full pt-6">
        <div className="w-full px-4">
          <div className="bg-white p-8 w-full shadow border">
            <h1 className="text-xl font-semibold">Barang Keluar</h1>
            <div className="w-full flex items-center gap-x-4 pt-8">
              <InputText
                placeholder="Cari barang"
                name="input"
                label="input"
                type="text"
                outline="box"
                icon={<FaSearch />}
                ref={inputRef}
                onChange={handleSearch}
                onKeyDown={handleKeyDown}
                className="rounded-md py-2 bg-blue-100/50 w-1/3"
              />
              <div className="italic text-center">{'(ctrl + f)'}</div>
            </div>
            <div className="w-[88%]">
              <Dropdown
                items={products}
                onSelect={handleSelectProduct}
                isVisible={isQuery}
                highlightedIndex={highlightedIndex}
              />
            </div>
            <div className="pt-8 pb-4 w-1/5">
              <div className="font-semibold">Filter Tanggal</div>
              <form onSubmit={filterDate} className='flex items-center gap-x-4 py-2' action="">
                <InputText
                  placeholder="Start Date"
                  className='py-2'
                  name="start_date"
                  label="start_date"
                  type="date"
                  outline="box"
                  icon={<FaCalendarAlt />}
                />
                <div className="text-lg"><FaArrowRight /></div>
                <InputText
                  placeholder="End Date"
                  className='py-2'
                  name="end_date"
                  label="end_date"
                  type="date"
                  outline="box"
                  icon={<FaCalendarAlt />}
                />
                <Button label="Cari" size="medium" icon={<FaSearch />} />
                <Button
                  onClick={() => {
                    setSelectedProduct(null);
                    setStart('');
                    setEnd('');
                    setPage(1);
                  }}
                  label="Reset"
                  size="medium"
                  icon={<TbReload />}
                />
              </form>
            </div>
            <div className="font-bold text-lg pb-2">Pencarian barang : {!selectedProduct ? 'Semua' : selectedProduct.name}</div>
            {/* Table */}
            <TableComponent
              datas={datas}
              tableHead={tableHead}
              aliases={aliases}
              onCellChange={() => { }}
              onSelectChange={() => { }}
              isEdit={isEdit}
              setIsEdit={setIsEdit}
            />
            <Pagination page={page} setPage={setPage} totalPages={totalPages} />
          </div>
        </div>
      </div>
    </Layout>
  );
}