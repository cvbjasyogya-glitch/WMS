import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import MainLayout from "../../layout/MainLayout";
import { formatToIDR, now } from "../../utils/utils";

export const PrintPage = () => {
    const { id: invoiceId } = useParams<{ id: string }>();
    const [datas, setDatas] = useState<any[]>([]);
    const cash = localStorage.getItem('tunai')
    const navigate = useNavigate();
    useEffect(() => {
        getInvoice();
    }, [])

    const getInvoice = async () => {
        try {
            const response = await (window as any).api.transaction.getByField('invoice_id', invoiceId);
            setDatas(response.data);
            console.log(response.data)
        } catch (error) {
            console.error(error);
        }
    }

    return (
        <div>
            <MainLayout>
                <div className="bg-slate-100 h-screen">
                    <button className="px-4 py-2 m-4 font-medium text-lg border border-gray-500 rounded" onClick={() => navigate('/dashboard')}>Kembali</button>
                    <div className="w-full flex flex-col items-center justify-centerac">
                        {/* PAPER PRINT */}
                        <div className="invoice  w-[188.98px] border flex flex-col bg-white">
                            <div className="px-2 py-4">
                                <div className="text-center pb-2">
                                    <div className="font-bold">BISMILLAH MART</div>
                                    <div className="">Taman Gading P-10 Jember</div>
                                </div>
                                <div className="border-t border-dashed border-black"></div>
                                <div className="flex flex-col gap-y-2 py-2">
                                    {datas && datas.map((item, index) => (
                                        <div key={index} className="item">
                                            <div className="uppercase">{item.products_name} {`[${item.units_name}]`}</div>
                                            <div className="flex justify-between">
                                                <div className="jml-harga">{`${item.product_qty} x ${(item.total_price / item.product_qty)}`}</div>
                                                <div className="">{`${formatToIDR(item.total_price)}`}</div>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                                <div className="border-t border-dashed border-black "></div>
                                <div className="item">
                                    <div className="flex justify-between py-2">
                                        <div className="font-bold ">Total</div>
                                        <div className="font-bold ">{formatToIDR(datas.reduce((total, item) => total + item.total_price, 0))}</div>
                                    </div>
                                    <div className="border-t border-dashed border-black "></div>
                                    <div className="flex justify-between py-2">
                                        <div className="">Cash</div>
                                        <div className="">{formatToIDR(parseInt(cash || datas.reduce((total, item) => total + item.total_price, 0), 10))}</div>
                                    </div>
                                    <div className="flex justify-between">
                                        <div className="">Kembali</div>
                                        <div className="">{formatToIDR(parseInt(cash || datas.reduce((total, item) => total + item.total_price, 0), 10) - datas.reduce((total, item) => total + item.total_price, 0))}</div>
                                    </div>
                                    <div className="text-center pt-3">{now()}</div>
                                </div>
                            </div>
                        </div>
                        <div className="flex justify-center">
                            <button
                                onClick={() => {
                                    window.electron.ipcRenderer.send('print', cash, datas, now())
                                }}
                                className="bg-sky-900 text-white py-2 px-12 mt-4 rounded"
                            >
                                Print
                            </button>
                        </div>
                    </div>
                </div>
            </MainLayout>
        </div>
    )
}