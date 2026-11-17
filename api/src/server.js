const express = require('express');
const rotas = require('./rotas');
const { encerrar } = require('./db');

const app = express();
const porta = Number(process.env.PORT || 3000);

app.use((req, res, next) => {
  const inicio = Date.now();
  const enviarJson = res.json.bind(res);
  res.json = (corpo) => {
    console.log(JSON.stringify({
      metodo: req.method,
      url: req.originalUrl,
      status: res.statusCode,
      duracao_ms: Date.now() - inicio,
      resposta: corpo,
    }));
    return enviarJson(corpo);
  };
  next();
});

app.use(rotas);

app.use((req, res) => {
  res.status(404).json({ erro: 'rota nao encontrada' });
});

app.use((erro, req, res, next) => {
  console.error(erro);
  res.status(500).json({ erro: 'erro interno' });
});

const servidor = app.listen(porta, () => {
  console.log(`API ouvindo na porta ${porta}`);
});

let encerrando = false;

function encerrarServidor() {
  if (encerrando) return;
  encerrando = true;

  servidor.close((erro) => {
    if (erro) {
      console.error('Erro ao encerrar o servidor HTTP:', erro);
      process.exitCode = 1;
    }

    encerrar().catch((erroPool) => {
      console.error('Erro ao encerrar o pool PostgreSQL:', erroPool);
      process.exitCode = 1;
    });
  });
}

process.once('SIGINT', encerrarServidor);
process.once('SIGTERM', encerrarServidor);
