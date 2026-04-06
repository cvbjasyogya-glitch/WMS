import { forwardRef } from 'react';
import { useSelector, useDispatch } from 'react-redux';
import { RootState } from '../../store/store';
import { setQuantity, removeFromCart, setSelectedConversion } from '../../reducers/cartReducer';
import { TableCart } from '../table/TableCart';

const Cart = forwardRef<HTMLTableElement, any>((props, ref) => {
    const cartItems = useSelector((state: RootState) => state.cart.items);
    const dispatch = useDispatch();
    const tableHead = ['No', 'Kode', 'Nama Barang', 'Satuan', 'Total Stok', 'Qty', 'Harga', 'Subtotal', 'Aksi'];

    const handleConversionChange = (cartId: string, itemId: number, conversionId: number | null) => {
        const price = conversionId
            ? cartItems.find((item) => item.id === itemId)?.conversions.find((conversion) => conversion.id === conversionId)?.sell_price ?? null
            : null;
        const conversionName = conversionId
            ? cartItems.find((item) => item.id === itemId)?.conversions.find((conversion) => conversion.id === conversionId)?.units_name ?? null
            : null;
        dispatch(setSelectedConversion({ cartId: cartId, id: itemId, conversionId, conversionName: conversionName, sell_price: price }));
    };

    const handleQuantityChange = (cartId: string, quantity: string) => {
        if (quantity === '') {
            dispatch(setQuantity({ cartId: cartId, qty: null }));
            return;
        }

        const qty = Number(quantity);
        if (qty < 0) return;
        dispatch(setQuantity({ cartId: cartId, qty }));
    };

    const handleRemoveItem = (cartId: string) => {
        if (cartId === undefined) return;
        dispatch(removeFromCart(cartId));
    };

    return (
        <div className="cart" ref={ref}>
            <TableCart
                tableHead={tableHead}
                cartItems={cartItems}
                handleConversionChange={handleConversionChange}
                handleQuantityChange={handleQuantityChange}
                handleRemoveItem={handleRemoveItem}
                ref={ref}
                focusedCell={props.focusedCell}
                setFocusedCell={props.setFocusedCell}
                dropDownRef={props.inputRef}
            />
        </div>
    );
});

export default Cart;