# Asahi Fan Control

Controlador local de ventoinhas para MacBook Pro Apple Silicon com Asahi Linux. Usa diretamente a interface `hwmon` do driver `macsmc-hwmon`, sem bibliotecas externas.

## Segurança

- Em curva automática, o SMC da Apple mantém o controlo abaixo do limiar de ativação.
- A partir do limiar, o controlador aplica a curva selecionada.
- Aos 92 °C força imediatamente 100%.
- Se perder todas as leituras de temperatura, força 100%.
- Quando o serviço termina, escreve `0` em `fanX_target` para devolver o controlo ao SMC.
- O watchdog do systemd reinicia o controlador se este deixar de responder.

O controlo manual é marcado como inseguro pelo próprio kernel, pois não existe uma garantia formal de recuperação em todos os tipos de falha. Usa-o com atenção.

## Instalação

No terminal, entra na pasta extraída e executa:

```bash
chmod +x install.sh uninstall.sh
sudo ./install.sh
```

Se o instalador pedir, reinicia o computador. Depois abre no navegador:

```text
http://127.0.0.1:8799
```

O painel só escuta em `127.0.0.1`: não fica acessível a partir da rede.
Também podes abri-lo pelo ícone **Asahi Fan Control** instalado no menu de aplicações do Fedora.

## Perfis

- **Silencioso:** o controlador assume aos 65 °C.
- **Equilibrado:** assume aos 55 °C.
- **Fresco:** assume aos 45 °C.
- **Manual:** 20–100%, mantendo a proteção de temperatura crítica.
- **SMC Apple:** controlo totalmente devolvido ao firmware.

## Diagnóstico

```bash
sudo /opt/asahi-fan-control/asahi_fan_control.py --check
systemctl status asahi-fan-control
journalctl -u asahi-fan-control -f
```

Se `control_available` aparecer como `false`, confirma o parâmetro suportado:

```bash
modinfo -p macsmc-hwmon
```

Nas versões atuais é `fan_control=1`; kernels Asahi mais antigos podem chamar-lhe `melt_my_mac=1`.

No Fedora Asahi, se o módulo for carregado pelo `initramfs`, ativa o parâmetro diretamente na linha de arranque e reinicia:

```bash
sudo grubby --update-kernel=ALL --args="macsmc_hwmon.fan_control=1"
sudo reboot
```

## Configuração

O ficheiro é `/etc/asahi-fan-control.json`. Podes alterar temperaturas, histerese, sensores considerados e porta do painel. Reinicia depois:

```bash
sudo systemctl restart asahi-fan-control
```

## Remoção

```bash
sudo ./uninstall.sh
```

O desinstalador preserva `/etc/asahi-fan-control.json` e devolve as ventoinhas ao SMC antes de remover o serviço.
