import { useEffect, useRef, forwardRef, useImperativeHandle } from "react";
import { formatToIDR } from "../../utils/utils";
import { FaTrashAlt } from "react-icons/fa";

interface TableCartProps {
    tableHead: string[];
    cartItems: any;
    handleConversionChange: (cartId: string, itemId: number, conversionId: number) => void;
    handleQuantityChange: (cartId: string, quantity: string) => void;
    handleRemoveItem: (cartId: string) => void;
    focusedCell: number;
    setFocusedCell: any;
    dropDownRef: any;
}

export const TableCart = forwardRef<any, TableCartProps>((props, ref) => {
    const { tableHead, cartItems, handleConversionChange, handleQuantityChange, handleRemoveItem, focusedCell, setFocusedCell } = props;
    const tableRef = useRef<HTMLTableElement>(null);
    const scrollContainerRef = useRef<HTMLDivElement>(null);
    const inputRefs = useRef<(HTMLElement | null)[]>([]);
    useImperativeHandle(ref, () => tableRef.current);
    const handleKeyDown = (event: KeyboardEvent) => {
        if (cartItems.length === 0 || (props.dropDownRef.current && props.dropDownRef.current.contains(document.activeElement))) return;

        switch (event.key) {
            case 'Delete':
                setFocusedCell((prev) => {
                    if (prev === null) return null
                    handleRemoveItem(cartItems[prev].cartId)
                    if (prev === 0) return null
                    return prev - 1
                })
                break;
            case 'ArrowDown':
                event.preventDefault();
                setFocusedCell((prev) => {
                    const nextIndex = (prev === null || prev === cartItems.length - 1) ? 0 : prev + 1;
                    const nextElement = inputRefs.current[nextIndex];

                    if (nextIndex === 0) {
                        if (scrollContainerRef.current) {
                            scrollContainerRef.current.scrollTo({ top: 0, behavior: 'smooth' });
                        }
                    } else {
                        if (nextElement) {
                            nextElement.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                        }
                    }

                    return nextIndex;
                });
                break;

            case 'ArrowUp':
                event.preventDefault();
                setFocusedCell((prev) => {
                    const nextIndex = (prev === null || prev === 0) ? cartItems.length - 1 : prev - 1;
                    const nextElement = inputRefs.current[nextIndex];
                    if (nextIndex === 1) {
                        if (scrollContainerRef.current) {
                            scrollContainerRef.current.scrollTo({ top: 0, behavior: 'smooth' });
                        }
                    } else {
                        if (nextElement) {
                            nextElement.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                        }
                    }

                    return nextIndex;
                });
                break;

            default:
                break;
        }
    };

    useEffect(() => {
        window.addEventListener('keydown', handleKeyDown);
        return () => {
            window.removeEventListener('keydown', handleKeyDown);
        };
    }, [cartItems.length]);

    useEffect(() => {
        if (focusedCell !== null) {
            inputRefs.current[focusedCell]?.focus();
        }
    }, [focusedCell]);
    return (
        <div ref={scrollContainerRef} className="h-[60vh] overflow-auto">
            <table ref={tableRef} className='w-full  overflow-auto border-2'>
                <thead className='bg-blue-400 text-white sticky top-0'>
                    <tr>
                        {tableHead.map((item, index) => <th className='p-4' key={index}>{item}</th>)}
                    </tr>
                </thead>
                <tbody>
                    {cartItems.length === 0 ? (
                        <tr>
                            <td colSpan={9} className="text-center text-gray-500">Kosong.</td>
                        </tr>
                    ) : (
                        cartItems.map((item: any, index: number) => (
                            <tr
                                onMouseEnter={() => setFocusedCell(index)}
                                onMouseLeave={() => setFocusedCell(0)}
                                className={`font-semibold ${focusedCell === index ? 'border border-blue-500' : ''}`}
                                key={index}
                            >
                                <td className={`p-4 border border-blue-500/30 ${focusedCell === index ? 'bg-blue-100/60' : ''}`}>{index + 1}</td>
                                <td className={`p-4 border border-blue-500/30 ${focusedCell === index ? 'bg-blue-100/60' : ''}`}>{item.barcode}</td>
                                <td className={`px-4 py-2 border border-blue-500/30 ${focusedCell === index ? 'bg-blue-100/60' : ''}`}>{item.name}</td>
                                <td className={`px-4 py-2 border border-blue-500/30 ${focusedCell === index ? 'bg-blue-100/60' : ''}`}>
                                    <select
                                        ref={(el) => (inputRefs.current[index] = el)}
                                        className="border-2 cursor-pointer w-full"
                                        value={item.selectedConversionId || ''}
                                        onChange={(e) => handleConversionChange(item.cartId, item.id, Number(e.target.value))}
                                    >
                                        <option value="" disabled>Pilih satuan</option>
                                        {item.conversions.map((conversion: any) => (
                                            <option disabled={item.is_stock_variant === 1 && conversion.stock === 0} className="flex justify-between" key={conversion.id} value={conversion.id}>
                                                {conversion.units_name} {item.is_stock_variant === 1 ? `[${conversion.stock}]` : ''}
                                            </option>
                                        ))}
                                    </select>
                                </td>
                                <td className={`px-4 py-2 border border-blue-500/30 ${focusedCell === index ? 'bg-blue-100/60' : ''}`}>
                                    {item.stock}
                                </td>
                                <td className={`px-4 py-2 border border-blue-500/30 ${focusedCell === index ? 'bg-blue-100/60' : ''}`}>
                                    <input
                                        type="number"
                                        min="0"
                                        step="any"
                                        value={item.quantity}
                                        onChange={(e) => handleQuantityChange(item.cartId, e.target.value)}
                                        className={`w-16 border-2 rounded p-1 ${item.is_stock_variant === 0 && item.stock <= 0 ? 'bg-gray-200' : ''}`}
                                        disabled={item.convertions || item.is_stock_variant === 0 && item.stock <= 0}
                                    />
                                </td>
                                <td className={`px-4 py-2 border border-blue-500/30 ${focusedCell === index ? 'bg-blue-100/60' : ''}`}>{formatToIDR(item.sell_price ?? 0)}</td>
                                {/* <td className={`px-4 py-2 border border-blue-500/30 ${focusedCell === index ? 'bg-blue-100/60' : ''}`}>{item.discount ? item.discount : 0}</td> */}
                                <td className={`px-4 py-2 border border-blue-500/30 ${focusedCell === index ? 'bg-blue-100/60' : ''}`}>
                                    {item.is_stock_variant === 1 || item.stock !== 0 ? formatToIDR((item.sell_price ?? 0) * (item.quantity || 1)) : 'N/A'}
                                </td>
                                <td className={`px-4 py-2 border border-blue-500/30 ${focusedCell === index ? 'bg-blue-100/60' : ''}`}>
                                    <button onClick={() => handleRemoveItem(item.cartId)} className="text-red-500 p-2"><FaTrashAlt size={20} /></button>
                                </td>
                            </tr>
                        ))
                    )}
                </tbody>
            </table>
        </div>
    );
});