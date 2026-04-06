import { PosPrintData } from '@plick/electron-pos-printer'
import { formatToIDR } from '../../renderer/src/utils/utils'
import moment, { now } from 'moment'

export const printdata = (cash: number, invoice: any) => {
  const kembali = cash - invoice.reduce((total: number, item: any) => total + item.total_price, 0)
  let dataTable: any = []

  invoice.map((item: any) => {
    dataTable.push([
      {
        type: 'text',
        value: `${item.products_name}[${item.units_name}]`,
        style: { fontFamily: 'VT323, monospace' }
      }
    ])
    dataTable.push([
      {
        type: 'text',
        value: `${item.product_qty}x${item.total_price / item.product_qty}`,
        style: { fontFamily: 'VT323, monospace' }
      },
      {
        type: 'text',
        value: formatToIDR(item.total_price),
        style: { fontFamily: 'VT323, monospace' }
      }
    ])
  })

  const data: PosPrintData[] = [
    {
      type: 'text',
      value: 'TOKO BISMILLAH',
      style: {
        fontWeight: '700',
        textAlign: 'center',
        fontSize: '12px',
        marginRight: '20px',
        paddingBottom: '10px',
        fontFamily: 'VT323, monospace'
      }
    },
    {
      type: 'text',
      value: 'Perum. Taman Gading P-10',
      style: {
        fontWeight: '700',
        textAlign: 'center',
        fontSize: '10px',
        marginRight: '20px',
        paddingBottom: '5px',
        fontFamily: 'VT323, monospace'
      }
    },
    {
      type: 'text',
      value: '.',
      style: {
        fontWeight: '700',
        textAlign: 'center',
        fontSize: '12px',
        marginRight: '20px',
        fontFamily: 'VT323, monospace',
        width: '100%',
        borderBottom: '1px dashed black'
      }
    },
    {
      type: 'text',
      value: '',
      style: {
        paddingBottom: '10px'
      }
    },
    {
      type: 'table',
      style: { border: '0px solid black', fontFamily: 'VT323, monospace' },
      tableHeader: [],
      tableBody: dataTable,
      tableFooter: [[]],
      tableHeaderStyle: {},
      tableBodyStyle: {},
      tableFooterStyle: {},
      tableHeaderCellStyle: {},
      tableBodyCellStyle: {
        fontWeight: 'bold',
        textAlign: 'left',
        fontSize: '10px'
      },
      tableFooterCellStyle: {}
    },
    {
      type: 'text',
      value: '.',
      style: {
        fontWeight: '700',
        textAlign: 'center',
        fontSize: '12px',
        marginRight: '20px',
        fontFamily: 'VT323, monospace',
        width: '100%',
        borderBottom: '1px dashed black'
      }
    },
    {
      type: 'table',
      style: {
        border: '0px solid black',
        fontFamily: 'VT323, monospace',
        marginTop: '20px',
        marginRight: '10px'
      },
      tableHeader: [],
      tableBody: [
        [
          { type: 'text', value: 'Total' },
          {
            type: 'text',
            value: formatToIDR(
              invoice.reduce((total: number, item: any) => total + item.total_price, 0)
            )
          }
        ],
        [
          { type: 'text', value: 'Bayar' },
          { type: 'text', value: formatToIDR(cash) }
        ],
        [
          { type: 'text', value: 'Kembali' },
          { type: 'text', value: formatToIDR(kembali) }
        ]
      ],
      tableFooter: [[]],
      tableHeaderStyle: {},
      tableBodyStyle: {},
      tableFooterStyle: {},
      tableHeaderCellStyle: {},
      tableBodyCellStyle: {
        fontWeight: 'bold',
        textAlign: 'left',
        fontSize: '10px'
      },
      tableFooterCellStyle: {}
    },
    {
      type: 'text',
      value: moment(now()).format('YYYY-MM-DD HH:mm:ss').toString(),
      style: {
        fontWeight: '700',
        textAlign: 'center',
        fontSize: '10px',
        marginRight: '20px',
        paddingBottom: '10px',
        fontFamily: 'VT323, monospace',
        marginTop: '20px'
      }
    },
    {
      type: 'text',
      value: '.',
      style: {
        textDecoration: 'underline',
        fontSize: '10px',
        textAlign: 'center',
        color: 'red',
        paddingBottom: '50px'
      }
    },
    {
      type: 'text',
      value: '.',
      style: {
        textDecoration: 'underline',
        fontSize: '10px',
        textAlign: 'center',
        color: 'red',
        paddingBottom: '20px'
      }
    }
  ]

  return data
}
