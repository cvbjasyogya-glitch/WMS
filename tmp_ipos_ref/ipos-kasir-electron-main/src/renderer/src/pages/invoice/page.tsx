import { useEffect, useRef, useState } from 'react';
import Layout from '../../layout/MainLayout';
import { TableComponent } from '../../components/table/TableComponent';
import { InputText } from '../../components/input/InputText';
import { FaArrowRight, FaSearch } from 'react-icons/fa';
import { TbReload } from "react-icons/tb";
import { useNavigate } from 'react-router-dom';
import { handleCtrlF, handleCtrlT } from '../../utils/keyboard';
import { Button } from '../../components/button/Button';
import { Pagination } from '../../components/pagination/Pagination';
import Dropdown from '../../components/dropdown/DropDown';
import moment from 'moment';
import { formatToIDR } from '../../utils/utils';

export function TransactionPage() {
  const [isEdit, setIsEdit] = useState(false);
  const [datas, setDatas] = useState<any[]>([]);
  const [page, setPage] = useState(1);
  const [customer, setCustomer] = useState<any[]>([]);
  const [selectedCustomer, setSelectedCustomer] = useState<any>(null);
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [isQuery, setIsQuery] = useState(false);
  const [highlightedIndex, setHighlightedIndex] = useState(-1);
  const [totalPages, setTotalPages] = useState(1);
  const [totalData, setTotalData] = useState(0);
  const [totalProfit, setTotalProfit] = useState(0);
  const [omzet, setOmzet] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  const tableHead = ['no', 'id', 'customers_name', 'users_name', 'total_price', 'order_date'];
  const aliases = { no: 'No', id: 'id', customers_name: 'Pembeli', users_name: 'Staff', total_price: 'Total Harga', order_date: 'Tanggal' };
  const LIMIT_PER_PAGE = 10;
  const now = moment().format('YYYY-MM-DD');

  localStorage.removeItem('tunai')

  useEffect(() => {
    getTotalPages().then(() => {
      fetchTransactions()
      fetchInvoices()
    });
    const handlerKey = (e: KeyboardEvent) => {
      handleCtrlF(e, inputRef);
      handleCtrlT(e, () => navigate('/point/add-customer'));
    };
    window.addEventListener('keydown', handlerKey);
    return () => {
      window.removeEventListener('keydown', handlerKey);
    };
  }, [navigate, page, selectedCustomer, start, end]);

  const filterDate = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const formData = new FormData(e.currentTarget);
    const start = formData.get('start_date');
    const end = formData.get('end_date');
    setStart(start as string);
    setEnd(end as string);
  };

  const fetchInvoices = async () => {
    const response = await (window.api as any).invoice.filterTime('order_date', now);
    console.log(response)
  }

  const fetchTransactions = async () => {
    try {
      let response: any;
      if (selectedCustomer) {
        response = await (window.api as any).invoice.getPaginated(page, LIMIT_PER_PAGE, selectedCustomer.id, 'customer_id', 'order_date', start == '' && end == '' ? now : start, end);
      } else {
        response = await (window.api as any).invoice.getPaginated(page, LIMIT_PER_PAGE, -1, null, 'order_date', start == '' && end == '' ? now : start, end);
      }
      const profit = response.data.reduce((total: number, item: any) => total + item.total_profit, 0);
      const totalOmzet = response.data.reduce((total: number, item: any) => total + item.total_price, 0);
      setTotalProfit(profit)
      setOmzet(totalOmzet)
      setDatas(response.data);
    } catch (error) {
      console.error(error);
    }
  };

  const getTotalPages = async () => {
    try {
      let id = selectedCustomer ? selectedCustomer.id : -1
      let field = selectedCustomer ? 'product_id' : null
      const totalRecordsResponse = await (window.api as any).invoice.count(id, field, 'order_date', start == '' && end == '' ? now : start, end);
      if (totalRecordsResponse.success) {
        setTotalData(totalRecordsResponse.data.count);
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
      const response = await (window.api as any).customer.find(query);
      setCustomer(response.data || []);
    } else {
      setCustomer([]);
      setIsQuery(false);
    }
  };

  const handleKeyDown = (event: React.KeyboardEvent) => {
    switch (event.key) {
      case 'ArrowDown':
        setHighlightedIndex(prevIndex => Math.min(prevIndex + 1, customer.length - 1));
        break;
      case 'ArrowUp':
        setHighlightedIndex(prevIndex => Math.max(prevIndex - 1, 0));
        break;
      case 'Enter':
        if (highlightedIndex >= 0) {
          inputRef.current!.value = '';
          inputRef.current?.blur();
          setPage(1);
          handleSelectProduct(customer[highlightedIndex]);
        }
        break;
      default:
        break;
    }
  };

  const handleSelectProduct = async (item: any) => {
    try {
      setIsQuery(false);
      setSelectedCustomer(item);
    } catch (error) {
      console.error(error);
    }
  };

  const rowEnter = (id: any) => {
    console.log(id)
    navigate(`/print/${id}`);
  };

  return (
    <Layout>
      <div className="flex bg-slate-100 min-h-[90vh] w-full pt-6">
        <div className="w-full px-4">
          <div className=" ">
            <div className="flex items-center gap-x-4 w-2/3 pr-4 text-white">
              <div className="bg-blue-600 p-8 mb-4 rounded-xl shadow border min-w-[15em]">
                <div className="text-start w-full">Total Transaksi</div>
                <div className="text-3xl  font-bold">{totalData}</div>
              </div>
              <div className="bg-blue-600 p-8 mb-4 rounded-xl shadow border min-w-[15em]">
                <div className="text-start w-full">Total Omzet</div>
                <div className="text-3xl  font-bold">{formatToIDR(omzet)}</div>
              </div>
              <div className="bg-blue-600 p-8 mb-4 rounded-xl shadow border min-w-[15em]">
                <div className="text-start w-full">Total Untung</div>
                <div className="text-3xl  font-bold">{formatToIDR(totalProfit)}</div>
              </div>
            </div>
          </div>
          <div className="bg-white p-8 w-full shadow border">
            <h1 className="text-xl font-semibold">Invoice</h1>
            <div className="flex">
              <div className="w-full flex items-center gap-x-4 pt-8">
                <InputText
                  placeholder="Cari pembeli"
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
            </div>
            <div className="w-[88%]">
              <Dropdown
                isCode={false}
                items={customer}
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
                />
                <div className="text-lg"><FaArrowRight /></div>
                <InputText
                  placeholder="End Date"
                  className='py-2'
                  name="end_date"
                  label="end_date"
                  type="date"
                  outline="box"
                />
                <Button label="Cari" size="medium" icon={<FaSearch />} />
                <Button
                  onClick={() => {
                    setSelectedCustomer(null);
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
            <div className="font-bold text-lg pb-2">Pencarian barang : {!selectedCustomer ? 'Semua' : selectedCustomer.name}</div>
            {/* Table */}
            <TableComponent
              rowEnter={rowEnter}
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