 #!/bin/bash
server_name=${1:-"parallel_works_insiders"}
rm -f "${HOME}/${server_name}.out"
nohup code-insiders tunnel --name "${server_name}" --accept-server-license-terms > "${HOME}/${server_name}.out" 2>&1 &
exit
