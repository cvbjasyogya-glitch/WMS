import { useDispatch, useSelector } from "react-redux";
import { useEffect, useRef, useState } from "react";
import MainLayout from "../../layout/MainLayout";
import { RootState } from "../../store/store";
import { formatToIDR, now } from "../../utils/utils";
import { InputText } from "../../components/input/InputText";
import { Button } from "../../components/button/Button";
import { useNavigate } from "react-router-dom";
import { Message } from "../../components/message/Message";
import { FaPrint, FaUser } from "react-icons/fa";
import { handleEsc } from "../../utils/keyboard";
import { v4 as uuidv4 } from 'uuid'
import { clearCart } from "../../reducers/cartReducer";

export const PaymentPage = () => {
    const containerRef = useRef<HTMLDivElement>(null);
    const inputRef = useRef<HTMLInputElement>(null);
    const formRef = useRef<HTMLFormElement>(null);
    const customerRef = useRef<HTMLInputElement>(null);
    const buttonRef = useRef<HTMLButtonElement>(null);
    const cartItems = useSelector((state: RootState) => state.cart.items);
    const [tunai, setTunai] = useState(0);
    const [customers, setCustomers] = useState<any[]>([]);
    const itemRefs = useRef<(HTMLDivElement | null)[]>([]);
    const [isQuery, setIsQuery] = useState(false);
    const [isPaymentSuccessful, setIsPaymentSuccessful] = useState(false);
    const [success, setSuccess] = useState("");
    const [error, setError] = useState("");
    const [user, setUser] = useState<any>({})
    const [selectedCustomer, setSelectedCustomer] = useState<any>(null);
    const [highlightedIndex, setHighlightedIndex] = useState(-1);
    const [invoideId, setInvoideId] = useState('');
    const selectedCustomerRef = useRef(selectedCustomer);
    const dispatch = useDispatch();

    const totalPrice = cartItems.reduce((total, item) => {
        if (item.is_stock_variant === 0 && item.stock === 0) return total;
        const price = item.sell_price ? item.sell_price : 0;
        return total + (price * (item.quantity ?? 0));
    }, 0);
    const navigate = useNavigate();
    const kembalian = tunai - totalPrice;
    let kembalianClass = "text-blue-500";
    if (kembalian < 0) {
        kembalianClass = "text-red-500";
    } else if (kembalian > 0) {
        kembalianClass = "text-green-500";
    }

    useEffect(() => {
        inputRef.current?.focus();
        const data = JSON.parse(sessionStorage.getItem('user') || '{}')
        setUser(data);
        containerRef.current?.addEventListener('keydown', (e) => { handleEsc(e, () => navigate('/dashboard')) });

        return () => {
            containerRef.current?.removeEventListener('keydown', (e) => { handleEsc(e, () => navigate('/dashboard')) })
        };
    }, []);

    useEffect(() => {
        selectedCustomerRef.current = selectedCustomer;
    }, [selectedCustomer]);

    const handlePayment = async (e: React.FormEvent<HTMLFormElement>) => {
        e.preventDefault();
        const tunai = inputRef.current?.value ? parseInt(inputRef.current.value) : 0;
        const currentKembalian = tunai - totalPrice;
        const currentCustomer = selectedCustomerRef.current;

        if (currentKembalian >= 0) {
            const total_price = cartItems.reduce((acc, item) => {
                return acc + ((item.sell_price ?? 0) * (item.quantity ?? 0));
            }, 0);

            const total_profit = cartItems.reduce((acc, item) => {
                return acc + (((item.sell_price ?? 0) - (item.purchase_price ?? 0)) * (item.quantity ?? 0));
            }, 0);

            const invoiceId = uuidv4()
            setInvoideId(invoiceId);

            const invoice = [{
                id: invoiceId,
                customer_id: currentCustomer?.id || null,
                staff_id: user.id,
                total_price: total_price,
                total_profit: total_profit,
                order_date: now(),
            }]

            const transactions = cartItems.map((item) => {
                return {
                    id: uuidv4(),
                    product_id: item.id,
                    product_qty: item.quantity,
                    invoice_id: invoiceId,
                    unit_id: (item.conversions.find((conversion) => conversion.id === item.selectedConversionId) as any).unit_id ?? null,
                    total_price: (item.sell_price ?? 0) * (item.quantity ?? 0),
                    order_date: now(),
                    discount_id: item.discount_id ? item.discount_id : null,
                    tax_id: item.tax_id ? item.tax_id : null,
                };
            });

            reduceStockConvertions();
            reduceStockProducts();

            // Post transactions and invoices to the API
            const invoiceRes = await (window.api as any).invoice.postMany(invoice)
            if (invoiceRes.success) {
                const transactionRes = await (window.api as any).transaction.postMany(transactions);
                console.log('transaction: ', transactionRes)
            }
            console.log('invoice: ', invoiceRes)

            // Set success message
            setSuccess("Pembayaran berhasil!");
            setIsPaymentSuccessful(true);
            setTimeout(() => setSuccess(""), 1000);

        } else {
            // Handle insufficient cash error
            setError("Jumlah tunai tidak cukup!");
            setTimeout(() => setError(""), 1000);
        }
    };

    const reduceStockConvertions = async () => {
        const convertionItem = cartItems.filter((item: any) => item.is_stock_variant === 1);
        if (convertionItem.length === 0) return

        const payload = convertionItem.map((item: any) => {
            return {
                id: item.selectedConversionId,
                stock: 0 - Number(item.quantity)
            }
        })

        const response = await (window.api as any).convertion.putMany(['id'], payload);
        console.log('reduce: ', response)
        if (response.success === false) console.error(response.message)
    }

    const reduceStockProducts = async () => {
        const productItem = cartItems.filter((item: any) => item.is_stock_variant === 0);
        if (productItem.length === 0) return

        const payload = productItem.map((item: any) => {
            return {
                id: item.id,
                stock: 0 - Number(item.quantity)
            }
        })

        const response = await (window.api as any).product.putMany(['id'], payload);
        console.log('reduce: ', response)

        if (response.success === false) console.error(response.message)
    }

    const handleKeyDown = (event: React.KeyboardEvent) => {
        switch (event.key) {
            case 'ArrowDown':
                setHighlightedIndex(prevIndex => Math.min(prevIndex + 1, customers.length - 1));
                break;
            case 'ArrowUp':
                setHighlightedIndex(prevIndex => Math.max(prevIndex - 1, 0));
                break;
            case 'Enter':
                if (highlightedIndex >= 0) {
                    customerRef.current!.value = customers[highlightedIndex].name;
                    customerRef.current?.blur();
                    setIsQuery(false);
                    setSelectedCustomer(customers[highlightedIndex]);
                }
                break;

            default:
                break;
        }
    };

    const handleSearch = async () => {
        setIsQuery(true);
        setHighlightedIndex(-1);
        const query = customerRef.current?.value || '';
        if (query) {
            const response = await (window.api as any).customer.find(query);
            setCustomers(response.data || []);
        } else {
            setCustomers([]);
            setIsQuery(false);
        }
    };

    const handleCustomerSelect = (customer: any) => {
        customerRef.current!.value = customer.name;
        setSelectedCustomer(customer);
        setCustomers([]);
        setIsQuery(false);
    };

    const handlePrint = () => {
        dispatch(clearCart())
        navigate(`/print/${invoideId}`);
    };

    return (
        <div ref={containerRef} className="bg-slate-100 min-h-screen">
            <MainLayout>
                <div className="flex flex-col justify-center items-center h-[90vh]">
                    <div className="w-[50em]">
                        <div className="flex flex-col gap-y-4 bg-white px-12 py-8 border-2 shadow">
                            <div className="flex flex-row-reverse justify-between items-center border p-4 text-2xl">
                                <div className="">Total</div>
                                <div className="text-4xl font-bold">{formatToIDR(totalPrice)}</div>
                            </div>
                            <form onSubmit={handlePayment} ref={formRef} action="">
                                <div className="flex flex-row-reverse justify-between items-center border p-4 text-2xl gap-x-8">
                                    <div className="w-1/2">Tunai</div>
                                    <InputText
                                        ref={inputRef}
                                        name="tunai"
                                        label="Tunai"
                                        placeholder="0"
                                        type="number"
                                        outline="box"
                                        className="text-4xl font-bold bg-gray-100 text-end"
                                        onChange={(e) => {
                                            setTunai(Number(e.target.value))
                                            localStorage.setItem('tunai', e.target.value)
                                        }}
                                    />
                                </div>
                                <div className="flex flex-row-reverse justify-between items-center border p-4 text-2xl gap-x-8">
                                    <div className="w-1/2">Pembeli</div>
                                    <div className="flex flex-col">
                                        <div className="relative">
                                            <InputText
                                                placeholder="Pembeli"
                                                name="input"
                                                label="input"
                                                type="text"
                                                outline="box"
                                                icon={<FaUser />}
                                                ref={customerRef}
                                                className="py-2 bg-blue-100/50 rounded"
                                                onChange={handleSearch}
                                                onKeyDown={handleKeyDown}
                                            />
                                            <div className="absolute bg-white top-full left-0 right-0 z-10 text-[20px]">
                                                {isQuery ? (
                                                    customers.length > 0 ? (
                                                        customers.map((item: any, index) => (
                                                            <div
                                                                key={index}
                                                                ref={(el) => (itemRefs.current[index] = el)}
                                                                className={`flex border-2 shadow items-center gap-x-12 border-b py-2 px-4 cursor-pointer hover:bg-blue-100 font-bold ${highlightedIndex === index ? 'bg-blue-100' : ''}`}
                                                                onClick={() => handleCustomerSelect(item)}
                                                            >
                                                                <div className="text-start w-1/2">{item.name}</div>
                                                            </div>
                                                        ))
                                                    ) : (
                                                        <div className="border-2 shadow">Tidak ada data</div>
                                                    )
                                                ) : null}
                                            </div>
                                        </div>
                                    </div>
                                </div>
                                <div className="flex flex-row-reverse justify-between items-center border p-4 text-2xl">
                                    <div className="">Kembalian</div>
                                    <div className={`text-4xl font-bold ${kembalianClass}`}>{formatToIDR(kembalian)}</div>
                                </div>
                                <div className="">
                                    {success && <Message text={success} variant='success' onClick={() => setSuccess('')} className='flex justify-between font-semibold text-lg bg-green-100/70 border border-green-300 rounded-md px-4 py-2 w-full' />}
                                    {error && <Message text={error} variant='danger' onClick={() => setError('')} className='flex justify-between font-semibold text-lg bg-red-100/70 border border-red-300 rounded-md px-4 py-2 w-full' />}
                                </div>
                                {!isPaymentSuccessful &&
                                    <div className="w-full flex justify-center">
                                        <Button ref={buttonRef} label="Bayar (Enter)" className="mt-4" />
                                    </div>
                                }
                            </form>
                            {isPaymentSuccessful && (
                                <Button label="Print" icon={<FaPrint size={20} />} className="mt-4" onClick={handlePrint} />
                            )}
                            <div className="mt-4 overflow-auto max-h-[20vh]">
                                <h2 className="text-xl font-bold">Daftar Item:</h2>
                                <ul className="list-disc pl-5  text-lg mt-2 p-2">
                                    {cartItems.map((item, index) => {
                                        const selectedConversion = item.conversions.find(conversion => conversion.id === item.selectedConversionId);
                                        const price = selectedConversion ? selectedConversion.sell_price : 0;
                                        const totalItemPrice = price * (item.quantity ?? 0);
                                        return (
                                            <li key={index} className="flex justify-between font-medium border-b py-2">
                                                <span>{item.name} (x{item.quantity} {item.conversionName})</span>
                                                <span>{formatToIDR(totalItemPrice)}</span>
                                            </li>
                                        );
                                    })}
                                </ul>
                            </div>
                        </div>
                    </div>
                    <div className="flex gap-x-4">
                        <Button variant="secondary" label="Kembali (Esc)" className="mt-4" onClick={() => navigate('/dashboard')} />
                    </div>
                </div>
            </MainLayout>
        </div>
    );
}