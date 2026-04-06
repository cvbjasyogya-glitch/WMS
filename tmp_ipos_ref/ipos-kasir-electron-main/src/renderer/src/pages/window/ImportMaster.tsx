import React, { useState } from 'react';
import { useDropzone } from 'react-dropzone';
import * as XLSX from 'xlsx';
import { MasterLayout } from '../../layout/MasterLayout';
import MainLayout from '../../layout/MainLayout';
import { FaCheck, FaUpload } from 'react-icons/fa';
import { FaSpinner } from 'react-icons/fa';
import { Button } from '../../components/button/Button';
import { useNavigate } from 'react-router-dom';

interface Props { }

const ImportMaster: React.FC<Props> = () => {
    const [loading, setLoading] = useState(false);
    const [progress, setProgress] = useState(0);
    const [completed, setCompleted] = useState(false);
    const navigate = useNavigate()
    const handleUpload = async (payload: any, section: string) => {
        const response = await (window as any).api[section].postMany(payload);
        if (response.success) console.log(section + ' Uploaded!')
        else console.error(response.error);
    }

    const categoryProcess = async (workbook: XLSX.WorkBook): Promise<{ kategoriData: { id: number; code: string; name: string }[]; kategoriMap: Record<string, number> }> => {
        const kategoriSheet = workbook.Sheets['kategori'];
        if (!kategoriSheet) {
            console.error('Sheet "kategori" tidak ditemukan');
            return { kategoriData: [], kategoriMap: {} };
        }
        const kategoriData = XLSX.utils.sheet_to_json<{ id: number; code: string; name: string }>(kategoriSheet);
        const kategoriMap: Record<string, number> = {};
        kategoriData.forEach(row => {
            kategoriMap[row.name] = row.id;
        });
        return { kategoriData, kategoriMap }
    };

    const tipeStockProcess = (workbook: XLSX.WorkBook): { tipeStockData: { id: number; name: string }[]; tipeStockMap: Record<string, number> } => {
        const tipeStockSheet = workbook.Sheets['tipe_stock'];
        if (!tipeStockSheet) {
            console.error('Sheet "tipe_stock" tidak ditemukan');
            return { tipeStockData: [], tipeStockMap: {} };
        }
        const tipeStockData = XLSX.utils.sheet_to_json<{ id: number; name: string }>(tipeStockSheet);
        const tipeStockMap: Record<string, number> = {};
        tipeStockData.forEach(row => {
            tipeStockMap[row.name] = row.id;
        });
        return { tipeStockData, tipeStockMap }
    }

    const satuanProcess = (workbook: XLSX.WorkBook): { satuanData: { id: number; name: string; factor: number }[]; satuanMap: Record<string, number> } => {
        const satuanSheet = workbook.Sheets['satuan'];
        if (!satuanSheet) {
            console.error('Sheet "satuan" tidak ditemukan');
            return { satuanData: [], satuanMap: {} };
        }
        const satuanData = XLSX.utils.sheet_to_json<{ id: number; name: string; factor: number }>(satuanSheet);
        const satuanMap: Record<string, number> = {};
        satuanData.forEach(row => {
            satuanMap[row.name] = row.id;
        });
        return { satuanData, satuanMap }
    }

    const productProcess = (workbook: XLSX.WorkBook): { productData: any[] } => {
        const productSheet = workbook.Sheets['product'];
        if (!productSheet) {
            console.error('Sheet "product" tidak ditemukan');
            return { productData: [] };
        }
        const productData = XLSX.utils.sheet_to_json<any>(productSheet);
        return { productData }
    }

    const onDrop = (acceptedFiles: File[]) => {
        const file = acceptedFiles[0];
        const reader = new FileReader();

        setLoading(true);
        setProgress(0);

        reader.onload = async (event) => {
            try {
                const data = new Uint8Array(event.target?.result as ArrayBuffer);
                const workbook = XLSX.read(data, { type: 'array' });

                const { kategoriData, kategoriMap } = await categoryProcess(workbook)
                await handleUpload(kategoriData, 'category');
                setProgress(20);
                const { tipeStockMap } = tipeStockProcess(workbook);
                setProgress(40);
                const { satuanData, satuanMap } = satuanProcess(workbook);
                await handleUpload(satuanData, 'unit');
                setProgress(60);
                const { productData } = productProcess(workbook);
                setProgress(80);

                const groupedProducts = productData.reduce((acc, product) => {
                    if (!acc[product.name]) {
                        acc[product.name] = {
                            id: product.id,
                            name: product.name,
                            stock: product.total_stock,
                            category_id: kategoriMap && kategoriMap[product.kategori] || null,
                            barcode: product.barcode,
                            is_stock_variant: tipeStockMap[product.tipe_stock],
                            purchase_price: product.beli || null,
                            satuan: [],
                        };
                    }

                    acc[product.name].satuan.push({
                        id: satuanMap[product.satuan],
                        name: product.satuan,
                        grosir: product.grosir || null,
                        jual_grosir: product.jual_grosir || 0,
                        jual_normal: product.jual_normal || null,
                    });
                    return acc;
                }, {} as Record<string, any>);

                const transformedProductData = Object.values(groupedProducts);
                let index = 1;
                const convertions = transformedProductData.flatMap((item: any) => {
                    return item.satuan.map((unit: any) => {
                        console.log(unit)
                        return {
                            id: index++,
                            product_id: item.id,
                            unit_id: unit.id,
                            stock: 0,
                            sell_price: unit.jual_normal || 0,
                            grosir: unit.grosir,
                            grosir_price: unit.jual_grosir
                        };
                    });
                });
                const products = transformedProductData.map((item: any) => {
                    return {
                        id: item.id,
                        name: item.name,
                        stock: 0,
                        category_id: item.category_id,
                        barcode: item.barcode,
                        is_stock_variant: item.is_stock_variant,
                        purchase_price: item.purchase_price || 0,
                    };
                })
                await handleUpload(products, 'product');
                await handleUpload(convertions, 'convertion');
                setProgress(100);
            } catch (error) {
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
                <MasterLayout title="Import Barang" desc="Anda dapat menambahkan data barang">
                    <div className="p-8 bg-slate-50 border">
                        <div className="py-4">
                            {loading ? (
                                <div className="flex flex-col items-center">
                                    {completed ?
                                        <div className='flex flex-col items-center'>
                                            <FaCheck className=" text-green-500 text-4xl mb-4" />
                                            <p className="text-lg text-gray-600">File berhasil diproses</p>
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

export { ImportMaster };