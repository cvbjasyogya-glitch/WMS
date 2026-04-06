import React, { useState } from 'react';
import { useDropzone } from 'react-dropzone';
import * as XLSX from 'xlsx';
import { MasterLayout } from '../../layout/MasterLayout';
import MainLayout from '../../layout/MainLayout';
import { FaUpload } from 'react-icons/fa';
import { FaSpinner } from 'react-icons/fa';
import { Button } from '../../components/button/Button';
import { useNavigate } from 'react-router-dom';
import { MdCancel, MdCheckCircle } from 'react-icons/md';

interface Props { }
type DataProcessResult =
    | { success: true; data: any[]; dataMap: Record<string, any>; error?: null }
    | { success: false; data: []; dataMap: {}; error: string };

const ImportPrice: React.FC<Props> = () => {
    const [loading, setLoading] = useState(false);
    const [progress, setProgress] = useState(0);
    const [completed, setCompleted] = useState(false);
    const [isSuccess, setIsSuccess] = useState(false);
    const [error, setError] = useState('');
    const navigate = useNavigate()
    const handleUpload = async (payload: any, paramId: string[], section: string): Promise<any> => {
        const response = await (window as any).api[section].putMany(paramId, payload);
        if (response.success === true) {
            console.log(section + ' Uploaded!')
            return { success: true, error: null }
        }
        else {
            console.error(response.error);
            return { success: false, error: response.error }
        }
    }

    const dataProcess = async (workbook: XLSX.WorkBook, sheet: string): Promise<DataProcessResult> => {
        try {
            const dataSheet = workbook.Sheets[sheet];
            if (!dataSheet) {
                const errorMessage = `Sheet ${sheet} tidak ditemukan`;
                console.error(errorMessage);
                return { success: false, data: [], dataMap: {}, error: errorMessage };
            }

            const data = XLSX.utils.sheet_to_json<any>(dataSheet);
            const dataMap: Record<string, any> = {};

            data.forEach(row => {
                dataMap[row.name] = row.id;
            });

            return { success: true, data, dataMap, error: null };
        } catch (error: any) {
            console.error(error);
            return { success: false, data: [], dataMap: {}, error: error.message || 'Unknown error' };
        }
    };

    const onDrop = (acceptedFiles: File[]) => {
        const file = acceptedFiles[0];
        const reader = new FileReader();

        setLoading(true);
        setProgress(0);

        reader.onload = async (event) => {
            try {
                const data = new Uint8Array(event.target?.result as ArrayBuffer);
                const workbook = XLSX.read(data, { type: 'array' });

                const { error: dataErr } = await dataProcess(workbook, 'tipe_stock');
                const { error: productErr, data: productData } = await dataProcess(workbook, 'product');
                const { error: unitErr, dataMap: unitMap } = await dataProcess(workbook, 'satuan');

                if (dataErr || productErr || unitErr) throw new Error('Gagal memproses file. Mohon cek ulang file')

                const groupedProducts = productData.reduce((acc, product) => {
                    if (!product.beli || product.beli === 0) return acc
                    if (!acc[product.name]) {
                        acc[product.name] = {
                            id: product.id,
                            purchase_price: product.beli || null,
                        };
                    }
                    return acc;
                }, {} as Record<string, any>);

                const groupedConvertionsPrice = productData.reduce((acc, product) => {
                    if (!product.jual_normal || product.jual_normal === 0) return acc
                    const key = `${product.name}_${unitMap[product.satuan]}`;
                    if (!acc[key]) {
                        acc[key] = {
                            product_id: product.id,
                            unit_id: unitMap[product.satuan],
                            sell_price: product.jual_normal || 0,
                        };
                    } else {
                        acc[key].sell_price = product.jual_normal || 0;
                    }
                    return acc;
                }, {} as Record<string, any>);

                const groupedGrosir = productData.reduce((acc, product) => {
                    if (!product.grosir || product.grosir === 0) return acc
                    const key = `${product.name}_${unitMap[product.satuan]}`;
                    if (!acc[key]) {
                        acc[key] = {
                            product_id: product.id,
                            unit_id: unitMap[product.satuan],
                            grosir: product.grosir || 0,
                        };
                    } else {
                        acc[key].grosir = product.grosir || 0;
                    }
                    return acc;
                }, {} as Record<string, any>);

                const groupedGrosirPrice = productData.reduce((acc, product) => {
                    if (!product.jual_grosir || product.jual_grosir === 0) return acc
                    const key = `${product.name}_${unitMap[product.satuan]}`;
                    if (!acc[key]) {
                        acc[key] = {
                            product_id: product.id,
                            unit_id: unitMap[product.satuan],
                            grosir_price: product.jual_grosir || 0,
                        };
                    } else {
                        acc[key].grosir_price = product.jual_grosir || 0;
                    }
                    return acc;
                }, {} as Record<string, any>);

                const productsPrice = Object.values(groupedProducts);
                const convertionsPrice = Object.values(groupedConvertionsPrice);
                const grosir = Object.values(groupedGrosir);
                const grosirPrice = Object.values(groupedGrosirPrice);

                if (productsPrice.length > 0) {
                    const { success: productUpload } = await handleUpload(productsPrice, ['id'], 'product')
                    if (!productUpload) throw new Error('Gagal upload file. "products"')
                }
                if (convertionsPrice.length > 0) {
                    const { success: convertionUpload } = await handleUpload(convertionsPrice, ['product_id', 'unit_id'], 'convertion')
                    if (!convertionUpload) throw new Error('Gagal upload file "convertions"."jual_normal"')
                }
                if (grosir.length > 0) {
                    const { success: grosirUpload } = await handleUpload(grosir, ['product_id', 'unit_id'], 'convertion')
                    if (!grosirUpload) throw new Error('Gagal upload file "convertions"."grosir"')
                }
                if (grosirPrice.length > 0) {
                    const { success: grosirPriceUpload } = await handleUpload(grosirPrice, ['product_id', 'unit_id'], 'convertion')
                    if (!grosirPriceUpload) throw new Error('Gagal upload file "convertions"."jual_grosir"')
                }

                setProgress(100);
                setIsSuccess(true);
            } catch (error: any) {
                setCompleted(true);
                setIsSuccess(false);
                setError(error.message);
                console.error('Error processing file:', error);
            } finally {
                setCompleted(true);
            }
        };

        reader.readAsArrayBuffer(file);
    };

    const { getRootProps, getInputProps, isDragActive } = useDropzone({
        onDrop,
        accept: {
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
            'application/vnd.ms-excel': ['.xls'],
        },
    });

    return (
        <MainLayout>
            <div className="bg-slate-100 min-h-screen">
                <MasterLayout title="Import Harga" desc="Anda dapat menambahkan data harga">
                    <div className="p-8 bg-slate-50 border">
                        <div className="py-4">
                            {loading ? (
                                <div className="flex flex-col items-center">
                                    {completed ?
                                        !isSuccess ?
                                            <div className='flex flex-col items-center'>
                                                <MdCancel className=" text-red-500 mb-4" size={48} />
                                                <p className="text-lg text-gray-600">{error}</p>
                                            </div> :
                                            <div className='flex flex-col items-center'>
                                                <MdCheckCircle className=" text-green-500 mb-4" size={48} />
                                                <p className="text-lg text-gray-600">File berhasil diupload.</p>
                                            </div>
                                        : <div>
                                            <FaSpinner className="animate-spin text-blue-500 text-4xl mb-4" />
                                            <p className="text-lg text-gray-600">Memproses file, mohon tunggu...</p>
                                        </div>}
                                    <div className="w-full bg-gray-200 rounded-full h-4 mt-4">
                                        <div
                                            className="bg-blue-500 h-4 rounded-full "
                                            style={{ width: `${progress}%` }}
                                        />
                                    </div>
                                    <p className="mt-2 font-bold text-gray-600 text-xl">{progress}%</p>
                                    {completed && <Button label="Kembali" className="mt-2" onClick={() => navigate(-1)} />}
                                </div>
                            ) : (
                                <div
                                    {...getRootProps()}
                                    className={`border-2 border-dashed rounded p-4 text-center cursor-pointer ${isDragActive ? 'border-blue-400' : 'border-gray-300'
                                        }`}
                                >
                                    <div className="q-full flex justify-center mb-4">
                                        <FaUpload size={48} className="text-gray-400" />
                                    </div>
                                    <input {...getInputProps()} />
                                    {isDragActive ? (
                                        <p className="text-lg">Drop file Anda di sini...</p>
                                    ) : (
                                        <p className="text-lg">
                                            Tarik dan jatuhkan file Excel Anda di sini, atau klik untuk mengunggah.
                                        </p>
                                    )}
                                </div>
                            )}
                        </div>
                    </div>
                </MasterLayout>
            </div>
        </MainLayout>
    );
};

export { ImportPrice };