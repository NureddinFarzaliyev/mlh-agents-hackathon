##!/usr/bin/env bash

# Simple CLI Tic-Tac-Toe (2 players)

board=( "1" "2" "3" "4" "5" "6" "7" "8" "9" )
current_player="X"
moves=0

print_board() {
  clear
  echo "Tic-Tac-Toe"
  echo
  echo " ${board[0]} | ${board[1]} | ${board[2]} "
  echo "---+---+---"
  echo " ${board[3]} | ${board[4]} | ${board[5]} "
  echo "---+---+---"
  echo " ${board[6]} | ${board[7]} | ${board[8]} "
  echo
}

check_win() {
  local p="$1"
  local wins=(
    "0 1 2" "3 4 5" "6 7 8"  # rows
    "0 3 6" "1 4 7" "2 5 8"  # cols
    "0 4 8" "2 4 6"          # diagonals
  )

  for combo in "${wins[@]}"; do
    read -r a b c <<< "$combo"
    if [[ "${board[a]}" == "$p" && "${board[b]}" == "$p" && "${board[c]}" == "$p" ]]; then
      return 0
    fi
  done
  return 1
}

is_valid_move() {
  local pos="$1"
  [[ "$pos" =~ ^[1-9]$ ]] || return 1
  local idx=$((pos - 1))
  [[ "${board[idx]}" != "X" && "${board[idx]}" != "O" ]]
}

switch_player() {
  if [[ "$current_player" == "X" ]]; then
    current_player="O"
  else
    current_player="X"
  fi
}

while true; do
  print_board
  echo "Player $current_player, choose a position (1-9):"
  read -r choice

  if ! is_valid_move "$choice"; then
    echo "Invalid move. Press Enter to try again..."
    read -r
    continue
  fi

  idx=$((choice - 1))
  board[idx]="$current_player"
  ((moves++))

  if check_win "$current_player"; then
    print_board
    echo "🎉 Player $current_player wins!"
    break
  fi

  if [[ $moves -eq 9 ]]; then
    print_board
    echo "It's a draw!"
    break
  fi

  switch_player
done
