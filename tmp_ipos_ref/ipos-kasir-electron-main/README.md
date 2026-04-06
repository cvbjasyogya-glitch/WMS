# iPos Sales

<p align="center"> <a href="https://www.typescriptlang.org/"> <img src="https://img.shields.io/badge/TypeScript-3178C6?style=for-the-badge&logo=typescript&logoColor=white"> <a href="https://react.dev/"> <img src="https://img.shields.io/badge/-ReactJs-61DAFB?logo=react&logoColor=white&style=for-the-badge"> </a> <a href="https://vite.dev/"> <img src="https://img.shields.io/badge/Vite-646CFF?style=for-the-badge&logo=Vite&logoColor=white"></a> <a href="https://tailwindcss.com/"> <img src="https://img.shields.io/badge/Tailwind_CSS-grey?style=for-the-badge&logo=tailwind-css&logoColor=38B2AC"> </a> <a href="https://www.electronjs.org/"> <img src="https://img.shields.io/badge/-Electron-3b82f6?logo=electron&logoColor=white&style=for-the-badge"> </a> <a href="https://www.electronjs.org/"> <img src="https://img.shields.io/badge/-Sqlite-1dae32?logo=sqlite&logoColor=white&style=for-the-badge"> </a> </p>

A native desktop application for iPos Sales Kasir System. It is designed to provide an easy and efficient way to manage sales transactions and inventory.

## Features

- **Sales Transaction Management**: Manage sales transactions, including adding, editing, and deleting transactions.
- **Inventory Management**: Manage inventory, including adding, editing, and deleting products.
- **Customer Management**: Manage customer information, including adding, editing, and deleting customers.
- **Reporting**: Generate reports on sales transactions and inventory.
- **Login and Authentication**: Secure the application with login and authentication features.

## Installation

1. Clone the repository:

```bash
git clone https://github.com/rosfandy/ipos-kasir-electron
```

2. Install dependencies:

```bash
cd iPos-Sales
npm install
```

3. Run Migrations:

```bash
knex migrate:latest
```

4. Run Seeder for Roles and Users:

```bash
knex seed:run
```

5. Build the application:

```bash
npm run build
```

6. Run the application:

```bash
npm run start
```
