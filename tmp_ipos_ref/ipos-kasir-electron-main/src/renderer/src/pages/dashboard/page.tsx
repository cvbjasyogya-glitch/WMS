import { FaSearch } from 'react-icons/fa';
import { InputText } from '../../components/input/InputText';
import MainLayout from '../../layout/MainLayout';
import { useEffect, useRef, useState } from 'react';
import Dropdown from '../../components/dropdown/DropDown';
import { getDatasByField } from '../../services/api';
import { useDispatch, useSelector } from 'react-redux';
import { addToCart } from '../../reducers/cartReducer';
import Cart from '../../components/cart/Cart';
import { formatToIDR } from '../../utils/utils';
import { RootState } from '../../store/store';
import { handleCtrlF } from '../../utils/keyboard';
import { Button } from '../../components/button/Button';
import { useNavigate } from 'react-router-dom';

export function DashboardPage() {
  const inputRef = useRef<HTMLInputElement>(null);
  const tableRef = useRef<HTMLTableElement>(null);
  const [products, setProducts] = useState<any[]>([]);
  const [isQuery, setIsQuery] = useState(false);
  const [highlightedIndex, setHighlightedIndex] = useState(-1);
  const dispatch = useDispatch();
  const [focusedCell, setFocusedCell] = useState<number | null>(null);
  const navigate = useNavigate();
  const cartItems = useSelector((state: RootState) => state.cart.items);
  const user = JSON.parse(sessionStorage.getItem('user') || '{}');

  const totalPrice = cartItems.reduce((total, item) => {
    if (item.is_stock_variant === 0 && item.stock === 0) return total;
    const price = item.sell_price ? item.sell_price : 0;
    return total + (price * (item.quantity ?? 0));
  }, 0);

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
          tableRef.current?.focus();
          inputRef.current?.blur();
          setFocusedCell(0);
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
      const res = await getDatasByField(item.id, 'convertion', 'product_id');
      dispatch(addToCart({ ...item, conversions: res.data }));
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
      if (response.data) {
        response.data.map((item: any) => {
          if (item.barcode == query) {
            handleSelectProduct(item);
            inputRef.current!.value = '';
            inputRef.current?.focus();
          }
        });
      }
      setProducts(response.data || []);
    } else {
      setProducts([]);
      setIsQuery(false);
    }
  };

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      handleCtrlF(event, inputRef);
      if (event.ctrlKey && event.key === 'Enter' && totalPrice > 0) {
        navigate('/payment');
      }
    };
    window.addEventListener('keydown', handler);
    return () => {
      window.removeEventListener('keydown', handler);
    };
  }, [totalPrice, navigate]);

  useEffect(() => {
    inputRef.current?.focus();
  }, [])

  return (
    <MainLayout>
      <div className="bg-slate-100 min-h-[90vh] w-full py-6 px-4">
        <div className="flex">
          {/* Input Section */}
          <div className="bg-white w-2/3 px-4 py-6 border">
            <div className="mb-4 font-semibold uppercase">cari barang</div>
            <div className="flex items-center">
              <InputText
                placeholder="Masukkan kode atau nama barang"
                name="input"
                label="input"
                type="text"
                outline="box"
                icon={<FaSearch />}
                ref={inputRef}
                className="py-2 bg-blue-100/50 w-full rounded"
                onChange={handleSearch}
                onKeyDown={handleKeyDown}
              />
              <div className="italic w-1/5 text-center">{'(ctrl + f)'}</div>
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
          {/* Price Section */}
          <div className="bg-white w-2/3 px-4 py-6 border">
            <div className="font-semibold text-xl">Total Price</div>
            <div className="text-end text-4xl font-bold">{formatToIDR(totalPrice)}</div>
          </div>
        </div>
        <div className="flex gap-x-4">
          <div className="bg-white border p-8 my-4 w-4/5">
            <Cart ref={tableRef} focusedCell={focusedCell} setFocusedCell={setFocusedCell} inputRef={inputRef} />
          </div>
          <div className="flex flex-col gap-y-4 bg-white border w-1/5 p-8 my-4">
            <Button
              label={'Bayar (Ctrl + Enter)'}
              disabled={totalPrice === 0}
              onClick={() => navigate('/payment')}
              className={`border-2 text-white rounded-lg p-4 text-sm flex gap-x-2 font-semibold 
                ${totalPrice === 0 ? 'bg-gray-300 hover:bg-gray-300 disabled' : 'bg-blue-500'}`}
            />
            <Button
              label={'Point Pelanggan (Ctrl + ' + (user.role_id !== 3 ? '4' : '3') + ')'}
              onClick={() => { }}
              className={`p-4 text-sm rounded-md`}
            />
            <Button
              label={'Transaksi (Ctrl + ' + (user.role_id !== 3 ? '5' : '4') + ')'}
              onClick={() => { }}
              className={`p-4 text-sm rounded-md`}
            />
            {user.role_id !== 3 && (
              <Button
                label={'Manajemen stok'}
                onClick={() => { }}
                className={`p-4 text-sm rounded-md`}
              />
            )}
          </div>
        </div>
      </div>
    </MainLayout>
  );
}